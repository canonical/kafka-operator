(how-to-deploy-on-eks)=
# How to deploy on EKS

[Amazon Elastic Kubernetes Service](https://aws.amazon.com/eks/) (EKS) is a popular, fully automated Kubernetes service. To access the EKS Web interface, go to [{spellexception}`console.aws.amazon.com/eks/home`](https://console.aws.amazon.com/eks/home).

## Install EKS and Juju tooling

Install [Juju](https://juju.is/docs/juju/install-juju) and the [`kubectl` CLI tools](https://kubernetes.io/docs/tasks/tools/) (that will be used for managing the Kubernetes cluster) via snap:

```shell
sudo snap install juju --channel 3.5/stable
sudo snap install kubectl --classic
```

Follow the installation guides for:

* [{spellexception}`eksctl`](https://eksctl.io/installation/) - the Amazon EKS CLI
* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) - the Amazon Web Services CLI

To check they are all correctly installed, you can run the commands below.

```shell
juju version
```

<details>

<summary>Output example</summary>

```shell
3.5.2-genericlinux-amd64
```

</details>

```shell
kubectl version --client
``` 

<details>

<summary>Output example</summary>

```shell
Client Version: v1.28.2
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
```

</details>

```shell
eksctl info
```

<details>

<summary>Output example</summary>

```shell
eksctl version: 0.159.0
kubectl version: v1.28.2
```

</details>

```shell
aws --version
```

<details>

<summary>Output example</summary>

```shell
aws-cli/2.13.25 Python/3.11.5 Linux/6.2.0-33-generic exe/x86_64.ubuntu.23 prompt/off
```

</details>

### Authenticate

Create an IAM account (or use legacy access keys) and login to AWS:

```shell
aws configure

AWS Access Key ID [None]: SECRET_ACCESS_KEY_ID
AWS Secret Access Key [None]: SECRET_ACCESS_KEY_VALUE
Default region name [None]: eu-west-3
Default output format [None]:
```

Verify that the CLI tool is correctly authenticating

```shell
aws sts get-caller-identity
```

<details>

<summary>Output example</summary>

```yaml
{
    "UserId": "1234567890",
    "Account": "1234567890",
    "Arn": "arn:aws:iam::1234567890:root"
}
```

</details>

## Create a new EKS cluster

Export the deployment name for further use:

```shell
export JUJU_NAME=eks-$USER-$RANDOM
```

This following examples in this guide will use the location `eu-west-3` and K8s `v.1.27` - feel free to change this for your own deployment.

<details>

<summary>Sample `cluster.yaml`</summary>

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
    name: ${JUJU_NAME}
    region: eu-west-3
    version: "1.27"
iam:
  withOIDC: true

addons:
- name: aws-ebs-csi-driver
  wellKnownPolicies:
    ebsCSIController: true

nodeGroups:
    - name: ng-1
      minSize: 3
      maxSize: 5
      iam:
        attachPolicyARNs:
        - arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy
        - arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy
        - arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
        - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
        - arn:aws:iam::aws:policy/AmazonS3FullAccess
      instancesDistribution:
        maxPrice: 0.15
        instanceTypes: ["m5.xlarge", "m5.2xlarge"] # At least two instance types should be specified
        onDemandBaseCapacity: 0
        onDemandPercentageAboveBaseCapacity: 50
        spotInstancePools: 2
```

</details>

Bootstrap EKS cluster with the following command:

```shell
eksctl create cluster -f cluster.yaml
```

<details>

<summary>Sample `cluster.yaml`</summary>

```shell
...
2023-10-12 11:13:58 [ℹ]  using region eu-west-3
2023-10-12 11:13:59 [ℹ]  using Kubernetes version 1.27
...
2023-10-12 11:40:00 [✔]  EKS cluster "eks-taurus-27506" in "eu-west-3" region is ready
```

</details>

## Bootstrap Juju on EKS

Add Juju K8s clouds:

```shell
juju add-k8s $JUJU_NAME
```

Bootstrap Juju controller:

```shell
juju bootstrap $JUJU_NAME
```

## Deploy Charms

Create a new Juju model, if needed:

```shell
juju add-model <MODEL_NAME>
```

```{note}
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
Kubernetes control plane is running at https://AAAAAAAAAAAAAAAAAAAAAAA.gr7.eu-west-3.eks.amazonaws.com
CoreDNS is running at https://AAAAAAAAAAAAAAAAAAAAAAA.gr7.eu-west-3.eks.amazonaws.com/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

</details>

```shell
eksctl get cluster -A
```

<details>

<summary>Output example</summary>

```shell
NAME            REGION      EKSCTL CREATED
eks-marc-9587	eu-west-3	True
```

</details>

```shell
kubectl get node
```

<details>

<summary>Output example</summary>

```shell
NAME                                           STATUS   ROLES    AGE     VERSION
ip-192-168-1-168.eu-west-3.compute.internal    Ready    <none>   5d22h   v1.27.16-eks-a737599
ip-192-168-45-234.eu-west-3.compute.internal   Ready    <none>   3h25m   v1.27.16-eks-a737599
ip-192-168-85-225.eu-west-3.compute.internal   Ready    <none>   5d22h   v1.27.16-eks-a737599
```

</details>

## Clean up

```{caution}
Always clean EKS resources that are no longer necessary -  they could be costly!
```

To clean the EKS cluster, resources and juju cloud, run the following commands:

```shell
juju destroy-controller $JUJU_NAME --yes --destroy-all-models --destroy-storage --force
juju remove-cloud $JUJU_NAME
```

List all services and then delete those that have an associated EXTERNAL-IP value (e.g. load balancers):

```shell
kubectl get svc --all-namespaces
kubectl delete svc <service-name> 
```

Next, delete the EKS cluster (As described on the [Deleting an Amazon EKS cluster](https://docs.aws.amazon.com/eks/latest/userguide/delete-cluster.html) page):

```shell
eksctl get cluster -A
eksctl delete cluster <cluster_name> --region eu-west-3 --force --disable-nodegroup-eviction
```

Finally, remove AWS CLI user credentials (to avoid forgetting and getting exposed to a risk of leaking credentials):

```shell
rm -f ~/.aws/credentials
```
