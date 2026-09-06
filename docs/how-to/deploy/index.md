---
myst:
  html_meta:
    description: "Deploy Charmed Apache Kafka on any platform - complete deployment guides via Juju CLI, Terraform, AWS, Azure, and Juju spaces."
---

(how-to-deploy-index)=
# Deploy

This section covers deploying Charmed Apache Kafka on VM and Kubernetes using
different methods and cloud platforms. Synchronized tabs retain the selected
substrate across guides.

**Deployment methods:**

* [via Juju CLI](how-to-deploy-anywhere)
* [via Terraform](how-to-deploy-terraform)

**Platform-specific guides:**

* [AWS](how-to-deploy-on-aws)
* [Azure](how-to-deploy-on-azure)
* [Juju Spaces (Machine)](how-to-deploy-spaces)
* [External connections (Kubernetes)](how-to-external-k8s-connection)

```{toctree}
:titlesonly:
:maxdepth: 2
:hidden:

via Juju CLI<deploy-anywhere.md>
via Terraform<deploy-terraform.md>
AWS<deploy-aws.md>
Azure<deploy-azure.md>
Spaces<deploy-spaces.md>
External K8s connections<../external-k8s-connection.md>
```
