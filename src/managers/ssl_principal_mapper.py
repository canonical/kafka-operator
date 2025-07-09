#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Apache Kafka SSL principal mappings."""

import logging
import re

logger = logging.getLogger(__name__)

DEFAULT_SSL_PRINCIPAL_MAPPING_RULES = "DEFAULT"


class NoMatchingRuleError(Exception):
    """Raised when there not a rule that matches a distinguished name."""


class Rule:
    """Python implementation of org.apache.kafka.common.security.ssl.SslPrincipalMapper.Rule.java."""

    BACK_REFERENCE_PATTERN = re.compile(r"\$(\d+)")

    def __init__(
        self,
        pattern: str | None = None,
        replacement: str | None = None,
        to_lower_case: bool = False,
        to_upper_case: bool = False,
    ):
        self.is_default = pattern is None
        self.pattern = re.compile(pattern) if pattern else None
        self.replacement = replacement
        self.to_lower_case = to_lower_case
        self.to_upper_case = to_upper_case

    def apply(self, distinguished_name: str) -> str | None:
        """Apply the rule to a distinguished name.

        Returns:
            the principal name if a rule matches or None
        """
        if self.is_default or self.pattern is None or self.replacement is None:
            return distinguished_name

        result = None
        m = self.pattern.match(distinguished_name)
        if m:
            result = self.pattern.sub(
                self.escape_literal_back_references(self.replacement, len(m.groups())),
                distinguished_name,
            )
        if self.to_lower_case and result is not None:
            result = result.lower()
        elif self.to_upper_case and result is not None:
            result = result.upper()
        return result

    def escape_literal_back_references(self, unescaped: str, num_capturing_groups: int) -> str:
        """Escape back references in the replacement value.

        From Kafka's SslPrincipalMapper.java:

        > If we find a back reference that is not valid, then we will treat it as a literal string.
        For example, if we have 3 capturing groups and the Replacement Value has the value is
        "I owe $8 to him", then we want to treat the $8 as a literal "$8", rather than attempting
        to use it as a back reference.
        """

        def repl(match):
            """For every $n match, if we have a capturing group n, then return backslash-n."""
            group_num = int(match.group(1))
            if 1 <= group_num <= num_capturing_groups:
                return f"\\{group_num}"
            else:
                # Treat as literal if group doesn't exist
                return f"${group_num}"

        return re.sub(self.BACK_REFERENCE_PATTERN, repl, unescaped)

    def __repr__(self):
        """Class representation."""
        if self.is_default:
            return "DEFAULT"
        buf = f"RULE:{self.pattern.pattern if self.pattern else ''}"
        if self.replacement is not None:
            buf += f"/{self.replacement}"
        if self.to_lower_case:
            buf += "/L"
        elif self.to_upper_case:
            buf += "/U"
        return buf


class SslPrincipalMapper:
    """Python implementation of org.apache.kafka.common.security.ssl.SslPrincipalMapper.java."""

    RULE_PATTERN = r"(DEFAULT)|RULE:((\\.|[^\\/])*)/((\\.|[^\\/])*)/([LU]?).*?|(.*?)"
    RULE_SPLITTER = re.compile(r"\s*(" + RULE_PATTERN + r")\s*(,\s*|$)")
    RULE_PARSER = re.compile(RULE_PATTERN)

    def __init__(self, ssl_principal_mapping_rules: str | None = None):
        self.rules: list[Rule] = self.parse_rules(self.split_rules(ssl_principal_mapping_rules))

    @staticmethod
    def split_rules(ssl_principal_mapping_rules: str | None = None) -> list[str]:
        """Split the rules from a string into a list of rules in string format."""
        if ssl_principal_mapping_rules is None:
            ssl_principal_mapping_rules = DEFAULT_SSL_PRINCIPAL_MAPPING_RULES
        result = []
        for match in SslPrincipalMapper.RULE_SPLITTER.finditer(
            ssl_principal_mapping_rules.strip()
        ):
            result.append(match.group(1))
        return result

    @staticmethod
    def parse_rules(rules: list[str]) -> list[Rule]:
        """Parse the rules from a list of string into Rule objects."""
        result: list[Rule] = []
        for rule in rules:
            matcher = SslPrincipalMapper.RULE_PARSER.match(rule)
            if not matcher:
                raise ValueError(f"Invalid rule: {rule}")
            if len(rule) != matcher.end():
                raise ValueError(
                    f"Invalid rule: `{rule}`, unmatched substring: `{rule[matcher.end():]}`"
                )
            # add a DEFAULT rule if empty
            if matcher.group(1) is not None:
                result.append(Rule())
            elif matcher.group(2) is not None:
                result.append(
                    Rule(
                        pattern=matcher.group(2),
                        replacement=matcher.group(4),
                        to_lower_case=matcher.group(6) == "L",
                        to_upper_case=matcher.group(6) == "U",
                    )
                )
        return result

    def get_name(self, distinguished_name: str) -> str:
        """Get the principal name from a distinguished name using the mapping rules."""
        for rule in self.rules:
            principal_name = rule.apply(distinguished_name)
            if principal_name is not None:
                return principal_name
        raise NoMatchingRuleError(f"No rules apply to {distinguished_name}, rules {self.rules}")

    def __repr__(self):
        """Class representation."""
        return f"SslPrincipalMapper(rules = {self.rules})"
