#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest

from managers.ssl_principal_mapper import SslPrincipalMapper

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.broker


def test_valid_rules():
    _test_valid_rule("DEFAULT")
    _test_valid_rule("RULE:^CN=(.*?),OU=ServiceUsers.*$/$1/")
    _test_valid_rule("RULE:^CN=(.*?),OU=ServiceUsers.*$/$1/L, DEFAULT")
    _test_valid_rule("RULE:^CN=(.*?),OU=ServiceUsers.*$/$1@$2/")
    _test_valid_rule("RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/L")
    _test_valid_rule("RULE:^cn=(.?),ou=(.?),dc=(.?),dc=(.?)$/$1@$2/U")
    _test_valid_rule("RULE:^CN=([^,ADEFLTU,]+)(,.*|$)/$1/")
    _test_valid_rule("RULE:^CN=([^,DEFAULT,]+)(,.*|$)/$1/")


def _test_valid_rule(rules):
    SslPrincipalMapper.parse_rules(SslPrincipalMapper.split_rules(rules))


def test_invalid_rules():
    invalid_rules = [
        "default",
        "DEFAUL",
        "DEFAULT/L",
        "DEFAULT/U",
        "RULE:CN=(.*?),OU=ServiceUsers.*/$1",
        "rule:^CN=(.*?),OU=ServiceUsers.*$/$1/",
        "RULE:^CN=(.*?),OU=ServiceUsers.*$/$1/L/U",
        "RULE:^CN=(.*?),OU=ServiceUsers.*$/L",
        "RULE:^CN=(.*?),OU=ServiceUsers.*$/U",
        "RULE:^CN=(.*?),OU=ServiceUsers.*$/LU",
    ]
    for rules in invalid_rules:
        with pytest.raises(ValueError):
            SslPrincipalMapper.parse_rules(SslPrincipalMapper.split_rules(rules))


def test_ssl_principal_mapper():
    rules = ", ".join(
        [
            "RULE:^CN=(.*?),OU=ServiceUsers.*$/$1/L",
            "RULE:^CN=(.*?),OU=(.*?),O=(.*?),L=(.*?),ST=(.*?),C=(.*?)$/$1@$2/L",
            "RULE:^cn=(.*?),ou=(.*?),dc=(.*?),dc=(.*?)$/$1@$2/U",
            "RULE:^.*[Cc][Nn]=([a-zA-Z0-9.]*).*$/$1/U",
            "DEFAULT",
        ]
    )
    mapper = SslPrincipalMapper(rules)
    assert "duke" == mapper.get_name("CN=Duke,OU=ServiceUsers,O=Org,C=US")
    assert "duke@sme" == mapper.get_name("CN=Duke,OU=SME,O=mycp,L=Fulton,ST=MD,C=US")
    assert "DUKE@SME" == mapper.get_name("cn=duke,ou=sme,dc=mycp,dc=com")
    assert "DUKE" == mapper.get_name("cN=duke,OU=JavaSoft,O=Sun Microsystems")
    assert "OU=JavaSoft,O=Sun Microsystems,C=US" == mapper.get_name(
        "OU=JavaSoft,O=Sun Microsystems,C=US"
    )


def _test_rules_splitting(expected, rules):
    mapper = SslPrincipalMapper(rules)
    assert f"SslPrincipalMapper(rules = {expected})" == str(mapper)


def test_rules_splitting():
    _test_rules_splitting("[]", "")
    _test_rules_splitting("[DEFAULT]", "DEFAULT")
    _test_rules_splitting("[RULE:/]", "RULE://")
    _test_rules_splitting("[RULE:/.*]", "RULE:/.*/")
    _test_rules_splitting("[RULE:/.*/L]", "RULE:/.*/L")
    _test_rules_splitting("[RULE:/, DEFAULT]", "RULE://,DEFAULT")
    _test_rules_splitting("[RULE:/, DEFAULT]", "  RULE:// ,  DEFAULT  ")
    _test_rules_splitting("[RULE:   /     , DEFAULT]", "  RULE:   /     / ,  DEFAULT  ")
    _test_rules_splitting("[RULE:  /     /U, DEFAULT]", "  RULE:  /     /U   ,DEFAULT  ")
    _test_rules_splitting(
        "[RULE:([A-Z]*)/$1/U, RULE:([a-z]+)/$1, DEFAULT]",
        "  RULE:([A-Z]*)/$1/U   ,RULE:([a-z]+)/$1/,   DEFAULT  ",
    )
    _test_rules_splitting("[]", ",   , , ,      , , ,   ")
    _test_rules_splitting("[RULE:/, DEFAULT]", ",,RULE://,,,DEFAULT,,")
    _test_rules_splitting("[RULE: /   , DEFAULT]", ",  , RULE: /   /    ,,,   DEFAULT, ,   ")
    _test_rules_splitting("[RULE:   /  /U, DEFAULT]", "     ,  , RULE:   /  /U    ,,  ,DEFAULT, ,")
    _test_rules_splitting("[RULE:\\/\\\\\\(\\)\\n\\t/\\/\\/]", "RULE:\\/\\\\\\(\\)\\n\\t/\\/\\//")
    _test_rules_splitting(
        "[RULE:\\**\\/+/*/L, RULE:\\/*\\**/**]", "RULE:\\**\\/+/*/L,RULE:\\/*\\**/**/"
    )
    _test_rules_splitting(
        "[RULE:,RULE:,/,RULE:,\\//U, RULE:,/RULE:,, RULE:,RULE:,/L,RULE:,/L, RULE:, DEFAULT, /DEFAULT, DEFAULT]",
        "RULE:,RULE:,/,RULE:,\\//U,RULE:,/RULE:,/,RULE:,RULE:,/L,RULE:,/L,RULE:, DEFAULT, /DEFAULT/,DEFAULT",
    )


def test_comma_with_whitespace():
    rules = r"RULE:^CN=((\\, *|\w)+)(,.*|$)/$1/,DEFAULT"
    mapper = SslPrincipalMapper(rules)
    assert "Tkac\\, Adam" == mapper.get_name("CN=Tkac\\, Adam,OU=ITZ,DC=geodis,DC=cz")
