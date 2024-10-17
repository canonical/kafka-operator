# How to deploy on AWS

[Amazon Web Services](https://aws.amazon.com/) is a popular subsidiary of Amazon that provides on-demand cloud computing platforms on a metered pay-as-you-go basis. Access the AWS web console at [console.aws.amazon.com](https://console.aws.amazon.com/).

## Summary
* [Install AWS and Juju tooling](#install-aws-and-juju-tooling)
  * [Authenticate](#authenticate)
* [Bootstrap Juju controller on AWS EC2](#bootstrap-juju-controller-on-aws-ec2)
* [Deploy charms](#deploy-charms)
* [Expose database (optional)](#expose-database-optional)
* [Clean up](#clean-up)

---

## Install AWS and Juju tooling

Install Juju via snap:
```shell
sudo snap install juju
```

Follow the installation guides for:
* [AWs CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) - the Amazon Web Services CLI

To check they are all correctly installed, you can run the commands demonstrated below with sample outputs:

```console
~$ juju version
3.5.4-genericlinux-amd64

~$ aws --version
aws-cli/2.13.25 Python/3.11.5 Linux/6.2.0-33-generic exe/x86_64.ubuntu.23 prompt/off
```
### Authenticate
[Create an IAM account](https://docs.aws.amazon.com/eks/latest/userguide/getting-started-console.html) (or use legacy access keys) to operate AWS EC2:
```shell
mkdir -p ~/.aws && cat <<- EOF >  ~/.aws/credentials.yaml
credentials:
  aws:
    NAME_OF_YOUR_CREDENTIAL:
      auth-type: access-key
      access-key: SECRET_ACCESS_KEY_ID
      secret-key: SECRET_ACCESS_KEY_VALUE
EOF
```

<!--- TODO, teach Juju to use `aws configure` format:
```shell
~$ aws configure
AWS Access Key ID [None]: SECRET_ACCESS_KEY_ID
AWS Secret Access Key [None]: SECRET_ACCESS_KEY_VALUE
Default region name [None]: eu-west-3
Default output format [None]:
```
Check AWS credentials:
```shell
~$ aws sts get-caller-identity
{
    "UserId": "1234567890",
    "Account": "1234567890",
    "Arn": "arn:aws:iam::1234567890:root"
}
```
--->

## Bootstrap Juju controller on AWS EC2

Add AWS credentials to Juju:
```shell
juju add-credential aws -f ~/.aws/credentials.yaml
```
Bootstrap Juju controller ([check all supported configuration options](https://juju.is/docs/juju/amazon-ec2)):
```shell
juju bootstrap aws <CONTROLLER_NAME>
```
[details="Output example"]
```shell
> juju bootstrap aws
Creating Juju controller "aws-us-east-1" on aws/us-east-1
Looking for packaged Juju agent version 3.5.4 for amd64
Located Juju agent version 3.5.4-ubuntu-amd64 at https://juju-dist-aws.s3.amazonaws.com/agents/agent/3.5.4/juju-3.5.4-linux-amd64.tgz
Launching controller instance(s) on aws/us-east-1...
 - i-0f4615983d113166d (arch=amd64 mem=8G cores=2)           
Installing Juju agent on bootstrap instance
Waiting for address
Attempting to connect to 54.226.221.6:22
Attempting to connect to 172.31.20.34:22
Connected to 54.226.221.6
Running machine configuration script...
Bootstrap agent now started
Contacting Juju controller at 54.226.221.6 to verify accessibility...

Bootstrap complete, controller "aws-us-east-1" is now available
Controller machines are in the "controller" model

Now you can run
	juju add-model <model-name>
to create a new model to deploy workloads.
```
[/details]

You can check the [AWS EC2 instance availability](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=running) (ensure the right AWS region chosen!):
![image|690x118](upload://putAO5NyHdaeWE6jXI8X1hZHTYv.png)

## Deploy charms

Create a new Juju model, if needed:
```shell
juju add-model <MODEL_NAME>
```
> (Optional) Increase the debug level if you are troubleshooting charms:
> ```shell
> juju model-config logging-config='<root>=INFO;unit=DEBUG'
> ```

Then, Charmed Kafka can be deployed as usual. However, note that the smallest instance types on Azure may not have enough resources for hosting 
a Kafka broker. We therefore recommend you to select some types that provides at the very least 8GB of RAM and 4 cores, although for production use-case
we recommend you to use the guidance provided in the [requirement page](/t/charmed-kafka-reference-requirements/10563). You can find more information about 
the available instance types in the [Azure web page](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview). 

```shell
juju deploy zookeeper -n3 --channel 3/stable
juju deploy kafka -n3 --constraints "instance-type=Standard_A4_v2" --channel 3/stable
juju integrate kafka zookeeper
```

We also recommend to deploy a [Data Integrator](https://charmhub.io/data-integrator) for creating an admin user to manage the content of the Kafka cluster:

```shell
juju deploy data-integrator admin --channel edge \
  --config extra-user-roles=admin \
  --config topic-name=admin-topic
```

And integrate it with the Kafka application:

```shell
juju integrate kafka admin
```

For more information on Data Integrator and how to use it, please refer to the [how-to manage applications](/t/charmed-kafka-how-to-manage-app/10285) user guide.

## Clean up

[note type="caution"]
Always clean AWS resources that are no longer necessary -  they could be costly!
[/note]

To destroy the Juju controller and remove AWS instance (warning: all your data will be permanently removed):
```shell
> juju controllers
Controller      Model  User   Access     Cloud/Region   Models  Nodes    HA  Version
aws-us-east-1*  -      admin  superuser  aws/us-east-1       1      1  none  3.5.4  

> juju destroy-controller aws-us-east-1 --destroy-all-models --destroy-storage --force
```

Next, check and manually delete all unnecessary AWS EC2 instances, to show the list of all your EC2 instances run the following command (make sure the correct region used!): 
```shell
aws ec2 describe-instances --region us-east-1 --query "Reservations[].Instances[*].{InstanceType: InstanceType, InstanceId: InstanceId, State: State.Name}" --output table
```
[details="Output example"]
```shell
-------------------------------------------------------
|                  DescribeInstances                  |
+---------------------+----------------+--------------+
|     InstanceId      | InstanceType   |    State     |
+---------------------+----------------+--------------+
|  i-0f374435695ffc54c|  m7i.large     |  terminated  |
|  i-0e1e8279f6b2a08e0|  m7i.large     |  terminated  |
|  i-061e0d10d36c8cffe|  m7i.large     |  terminated  |
|  i-0f4615983d113166d|  m7i.large     |  terminated  |
+---------------------+----------------+--------------+
```
[/details]

List your Juju credentials:
```shell
> juju credentials
...
Client Credentials:
Cloud        Credentials
aws          NAME_OF_YOUR_CREDENTIAL
...
```
Remove AWS EC2 CLI credentials from Juju:
```shell
> juju remove-credential aws NAME_OF_YOUR_CREDENTIAL
```

Finally, remove AWS CLI user credentials (to avoid forgetting and leaking):
```shell
rm -f ~/.aws/credentials.yaml
```
