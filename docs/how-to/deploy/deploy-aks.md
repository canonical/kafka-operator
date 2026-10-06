(how-to-deploy-on-aks)=
# How to deploy on AKS

[Azure Kubernetes Service](https://learn.microsoft.com/en-us/azure/aks/) (AKS) allows you to quickly deploy a production ready Kubernetes cluster in Azure. To access the AKS Web interface, go to [https://portal.azure.com/](https://portal.azure.com/).

## Install Client Environment

Client environment includes:
* Juju
* Azure CLI

### Juju 

Install Juju via snap:

```shell
sudo snap install juju --channel 3.5/stable
```

Check that the Juju version is correctly installed:

```shell
juju version
```

<details>

<summary>Output example</summary>

```text
3.5.2-genericlinux-amd64
```

</details>

### Azure CLI

Follow the [user guide](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt) for installing the Azure CLI on Linux distributions.

Verify that it is correctly installed running the command below:

```shell
az --version
```

<details>

<summary>Output example</summary>

```text
azure-cli                         2.65.0

core                              2.65.0
telemetry                          1.1.0

Dependencies:
msal                              1.31.0
azure-mgmt-resource               23.1.1

Python location '/opt/az/bin/python3'
Extensions directory '/home/deusebio/.azure/cliextensions'

Python (Linux) 3.11.8 (main, Sep 25 2024, 11:33:44) [GCC 11.4.0]

Legal docs and information: aka.ms/AzureCliLegal


Your CLI is up-to-date.
```

</details>

## Create AKS cluster

Login to your Azure account:

```shell
az login
```

Create a new [Azure Resource Group](https://learn.microsoft.com/en-us/cli/azure/manage-azure-groups-azure-cli):

```shell
az group create --name <RESOURCE_GROUP> --location <LOCATION>
```

The placeholder `<RESOURCE_GROUP>` can be a label of your choice, and it will be used to tag
the resources created on Azure. Also the following guide will use the single server AKS, 
using  `LOCATION=eastus` - but feel free to change this for your own deployment.

Bootstrap AKS with the following command (increase nodes count/size if necessary):

```shell
az aks create -g <RESOURCE_GROUP> -n $<K8S_CLUSTER_NAME> --enable-managed-identity --node-count 1 --node-vm-size=<INSTANCE_TYPE> --generate-ssh-keys
```

```{caution}
We recommend selecting an instance type that provides at the very least `16` GB of RAM and `4` cores, e.g. `Standard_A4_v4`.
You can find more information about the available instance types in the [Azure documentation](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview).
```

<details>

<summary>Output example</summary>

```yaml
{
  "aadProfile": null,
  "addonProfiles": null,
  "agentPoolProfiles": [
    {
      "availabilityZones": null,
      "capacityReservationGroupId": null,
      "count": 1,
      "creationData": null,
      "currentOrchestratorVersion": "1.28.9",
      "enableAutoScaling": false,
      "enableEncryptionAtHost": false,
      "enableFips": false,
      "enableNodePublicIp": false,
...
```

</details>

Dump newly bootstrapped AKS credentials:

```shell
az aks get-credentials --resource-group <RESOURCE_GROUP> --name <K8S_CLUSTER_NAME> --context aks
```

<details>

<summary>Output example</summary>

```shell
...
Merged "aks" as current context in ~/.kube/config
```

</details>

You can verify that the cluster and your client `kubectl` CLI is correctly configured by running a simple command, such as:

```shell
kubectl get pod -A
```

which should provide the list of the pod services running. 

## Bootstrap Juju controller on AKS

Bootstrap Juju controller:

```shell
juju bootstrap aks <CONTROLLER_NAME>
```

<details>

<summary>Output example</summary>

```shell
Creating Juju controller "aks" on aks/eastus
Bootstrap to Kubernetes cluster identified as azure/eastus
Creating k8s resources for controller "controller-aks"
Downloading images
Starting controller pod
Bootstrap agent now started
Contacting Juju controller at 20.231.233.33 to verify accessibility...

Bootstrap complete, controller "aks" is now available in namespace "controller-aks"

Now you can run
	juju add-model <model-name>
to create a new model to deploy k8s workloads.
```

</details>

## Deploy Charms

Create a new Juju model, if needed:

```shell
juju add-model <MODEL_NAME>
```

```{caution}
(Optional) Increase the debug level if you are troubleshooting charms:
```shell
juju model-config logging-config='<root>=INFO;unit=DEBUG'
```
```

Then, Charmed Apache Kafka K8s can be deployed as usual:

```shell
juju deploy zookeeper-k8s -n3 --channel 3/stable --trust
juju deploy kafka-k8s -n3 --channel 3/stable --trust
juju integrate kafka-k8s zookeeper-k8s
```

We also recommend to deploy a [Data Integrator](https://charmhub.io/data-integrator) for creating an admin user to manage the content of the Kafka cluster:

```shell
juju deploy data-integrator admin --channel edge \
  --config extra-user-roles=admin \
  --config topic-name=admin-topic
```

And integrate it with the Kafka application:

```shell
juju integrate kafka-k8s admin
```

For more information on Data Integrator and how to use it, please refer to the [how-to manage applications](how-to-manage-applications) user guide.

## Display deployment information

Display information about the current deployments with the following commands:

```shell
kubectl cluster-info 
```

<details>

<summary>Output example</summary>

```shell
Kubernetes control plane is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443
CoreDNS is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
Metrics-server is running at https://aks-user-aks-aaaaa-bbbbb.hcp.eastus.azmk8s.io:443/api/v1/namespaces/kube-system/services/https:metrics-server:/proxy
```

</details>

```
az aks list
```
<details>

<summary>Output example</summary>

```shell
...
        "count": 1,
        "currentOrchestratorVersion": "1.28.9",
        "enableAutoScaling": false,
...
```

</details>

```shell
kubectl get node
```

<details>

<summary>Output example</summary>

```shell
NAME                                STATUS   ROLES   AGE   VERSION
aks-nodepool1-31246187-vmss000000   Ready    agent   11m   v1.28.9
```

</details>

## Clean up

```{caution}
Always clean AKS resources that are no longer necessary -  they could be costly!
```

To clean the AKS cluster, resources and juju cloud, run the following commands:

```shell
juju destroy-controller <CONTROLLER_NAME> --destroy-all-models --destroy-storage --force
```

List all services and then delete those that have an associated EXTERNAL-IP value (load balancers, ...):

```shell
kubectl get svc --all-namespaces
kubectl delete svc <SERVICE_NAME> 
```

Next, delete the AKS resources (source: [Deleting an all Azure VMs](https://learn.microsoft.com/en-us/cli/azure/delete-azure-resources-at-scale#delete-all-azure-resources-of-a-type)):

```shell
az aks delete -g <RESOURCE_GROUP> -n <K8S_CLUSTER_NAME>
```

Finally, logout from AKS to clean the local credentials (to avoid forgetting and getting exposed to a risk of leaking credentials):

```shell
az logout
```
