# How to deploy on Azure

[Azure](https://azure.com/) is the cloud computing platform developed by Microsoft. It has management, access and development of applications and services to individuals, companies, and governments through its global infrastructure. Access the Azure web console at [portal.azure.com](https://portal.azure.com/).

## Summary
* [Install Azure and Juju tooling](#install-azure-and-juju-tooling)
  * [Authenticate](#authenticate)
* [Bootstrap Juju controller on Azure](#bootstrap-juju-controller-on-azure)
* [Deploy charms](#deploy-charms)
* [Clean up](#clean-up)

---

## Install Client Environment

> **WARNING**: The current limitations:
> * Only supported starting Juju 3.6 (currently edge)
> * Juju cli should be on Azure VM for it to be able to reach cloud metadata endpoint.
> * Managed Identity and the Juju resources should be on the same Azure subscription
> * The current setup has been tested on Ubuntu 22.04+

### Juju 

Install Juju via snap:

```shell
sudo snap install juju --channel 3.6/edge
```

Check that the Juju version is correctly installed:

```shell
juju version
```

which should show:

```shell
3.6-rc1-genericlinux-amd64
```

### Azure CLI

Follow the [user guide](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt) for installing the Azure CLI on Linux distributions.

Verify that it is correctly installed running the command below:

```shell
az --version
```

which should show the following output:

```shell
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

### Authenticate

> For more information on how to authenticate, refer to the [Juju documentation](/t/the-microsoft-azure-cloud-and-juju/1086) and [a dedicated user guide on how to register Azure on Juju](/t/how-to-use-juju-with-microsoft-azure/15219).

First of all, retrieve your subscription-id

```shell
az login
```

After providing the authentication via web browser, you will be shown a list of information and a table with the subscriptions connected to your user, e.g.:

```shell

...

No     Subscription name                     Subscription ID                       Tenant
-----  ------------------------------------  ------------------------------------  -------------
[1] *  <subscription_name>                   <subscription_id>                     canonical.com
[2]    <other_subscription_name>             <other_subscription_id>               canonical.com

...

```

In the prompt, select the subscription id you would like to connect the controller to, and store the id 
as it will be needed in the next step when bootstrapping the controller. 

### Bootstrap Juju controller on Azure

First, you need to add a set of credentials to your Juju client:

```shell
juju add-credentials azure
```

This will start a script that will help you set up the credentials, where you will be asked:

* `credential-name`: fill it with a sensible name that will help you identify the credential set, say `<CREDENTIAL_NAME>`
* `region`: select any default region is more convenient for you to deploy your controller and applications. Note that credentials are nevertheless not region specific
* `auth type`: select `interactive`, which is the recommended way to authenticate to Azure using Juju
* `subscription_id`: use the value `<subscription_id>` taken in the previous step
* `application_name`: please generate a random string to avoid collision with other users or applications
* `role-definition-name`: please generate a random string to avoid collision with other users or applications, and store it as `<AZURE_ROLE>`

After prompting all these information, you will be asked to authenticate the requests via web browser, as shown in the 
outputs that will display

```shell
To sign in, use a web browser to open the page https://microsoft.com/devicelogin and enter the code <YOUR_CODE> to authenticate.
```

In the browser, open the [authentication page](https://microsoft.com/devicelogin) and enter the code `<YOUR_CODE>` provided in the output. 

You will be asked to authenticate twice, for allowing the creation of two different resources in Azure.

If everything was fine, you will be confirmed that the credentials have been correctly added locally:

```shell
Credential <CREDENTIAL_NAME> added locally for cloud "azure".
```

Once the credentials are correctly added, we can bootstrap a controller

```shell
juju bootstrap azure <CONTROLLER_NAME>
```

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
Always clean Azure resources that are no longer necessary -  they could be costly!
[/note]

To destroy the Juju controller and remove Azure instance (warning: all your data will be permanently removed):
```shell
juju destroy-controller <CONTROLLER_NAME> --destroy-all-models --destroy-storage --force
```

> Use `juju list-controllers` to retrieve the names of the controllers that have been registered to your local client. 

Next, check and manually delete all unnecessary Azure VM instances, to show the list of all your Azure VMs run the following command (make sure the correct region used!): 
```shell
az resource list
```

List your Juju credentials:
```shell
> juju credentials
...
Client Credentials:
Cloud        Credentials
azure        NAME_OF_YOUR_CREDENTIAL
...
```
Remove Azure CLI credentials from Juju:
```shell
> juju remove-credential azure NAME_OF_YOUR_CREDENTIAL
```

After deleting the credentials, the `interactive` process may still leave the role resource and its assignment hanging around. 
We recommend you to check if these are still present by 

```shell
az role definition list --name <AZURE_ROLE>
```

Or also use it without specifying the `--name` argument to get the full list. You can also check whether you still have a 
role assignment bound to `<AZURE_ROLE>` registered using

```shell
az role assignment list --role <AZURE_ROLE>
```

If this is the case, you can remove the role assignment first and then the role itself with the following commands:

```shell
az role assignment delete --role <AZURE_ROLE>
az role definition delete --name <AZURE_ROLE>
```


Finally, logout Azure CLI user credentials to prevent any credential leakage:
```shell
az logout 
```

