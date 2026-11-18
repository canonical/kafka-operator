---
myst:
  html_meta:
    description: Deploy Canonical Managed Apache Kafka on Azure - complete the Azure portal deployment wizard, receive the confirmation email, and connect a client.
---

(how-to-deploy-azure-managed)=

# How to deploy Managed Apache Kafka on Azure

This guide shows how to deploy Canonical Managed Apache Kafka, a Charmed Apache Kafka deployment
operated by Canonical, into your Azure subscription. You configure the deployment in a seven-step
wizard in the Azure portal; the whole process takes about 30 minutes.

For the architecture of the deployment and the meaning of the options below, see
[Managed Apache Kafka on Azure](explanation-azure-managed). To deploy and operate Charmed Apache
Kafka on Azure yourself, see [How to deploy on Azure](how-to-deploy-on-azure) instead.

## Prerequisites

- An Azure subscription where you can create resource groups and managed applications.
- Enough vCPU quota in the target region for the VM sizes and counts you plan to select.
- Optional: an existing Azure virtual network (VNet) and subnet to peer with your client
  applications. Its address range must not overlap with the range that the deployment reserves in
  the managed resource group. The **Network** step of the wizard shows this range.
- Optional: an existing control plane from the Canonical Managed Juju deployment offering, in the
  same subscription.

## Open the deployment wizard

1. Open the
   [Canonical Managed Apache Kafka offering](https://portal.azure.com/#create/canonical.managed-kafkaself-service)
   in the Azure portal.
2. Review the service scope and pricing.
3. Select a **Plan** and click **Create**.

The wizard opens on its first step, **Basics**. The tabs at the top show all seven steps:

```{figure} images/azure-managed-wizard-basics.png
---
alt: The Basics step of the deployment wizard, with the tabs Basics, 
  Configuration, Additional Components, Network, Access, Feedback, and Review + 
  submit at the top.
---
The first step of the deployment wizard
```

Complete the steps below in order. Click **Next** at the bottom of each step to continue to the next
one.

### Step 1: Basics

1. Select the target **Subscription**.
2. Select a **Resource group** for the managed application resource, or click **Create new**.
3. Select the **Deployment location**.
4. Enter the administrator **User Name** and **User Email**. Canonical sends the endpoints and
   credentials to this email address.
5. Enter the **Application Name**.
6. Optional: change the name of the **Managed Resource Group**. See
   [Resource groups](explanation-azure-managed-resource-groups).

### Step 2: Configuration

1. In **Reuse an existing control plane deployment?**, select:
   - **No** to provision a new control plane. Then, in **Number of VMs for control plane**, select
     `3` for production or `1` for non-production environments.
   - **Yes** to reuse your existing control plane. See
     [Control plane](explanation-azure-managed-control-plane).
2. Optional: click **Change size** to change the **Control plane instance size**.
3. Review the **Management instance size**.
4. Set the **Broker Count**: `3` or more for production or `1` for non-production environments.
5. Select the **Disk Type** for the brokers.
6. Optional: click **Change size** to change the **Broker VM Size**.
7. Optional: select **Check vCPU quota** to verify the capacity of your subscription before the
   deployment starts.

For how the VM counts affect the SLA, see
[High availability](explanation-azure-managed-high-availability).

```{important}
If you keep the `Ephemeral` disk type for a production deployment, select
**Enable separate Apache KRaft instances** in the next step. See
[Apache Kafka brokers](explanation-azure-managed-brokers).
```

### Step 3: Additional Components

1. Select the components to enable:

   - **Enable separate Apache KRaft instances**
   - **Enable UI** for Kafka UI
   - **Enable Karapace**
   - **Enable Apache Kafka Connect**

   For what each component does, see [Controller VMs](explanation-azure-managed-controller-vms).

2. If you enabled any component, configure the **Controller instances** that host them:

   1. Set the **Number of VMs for the controllers**: an odd number, `3` or more for production or
      `1` for non-production environments.
   2. Select the **Disk Type** and the **Disk Size**.
   3. Optional: click **Change size** to change the **Controller VM Size**.

3. Optional: select **Check vCPU quota**.

### Step 4: Network

In **Network connectivity**, select how client applications reach the brokers and Kafka UI. For a
comparison of the options, see [Network connectivity](explanation-azure-managed-network).

- To peer with an existing Azure virtual network, select **Network peering**. Then select the
  existing VNet and subnet of your client applications. The wizard doesn't create them, so they must
  exist before you deploy. Make sure that their address range doesn't overlap with the range shown
  in the warning on this step, which the deployment uses for the managed resource group.
- To use public IP addresses, select **Public IPs**. Then, in **Allowed IPv4 CIDR sources for Apache
  Kafka brokers and UI**, replace `0.0.0.0/0` with the CIDR ranges of your client applications.

### Step 5: Access

1. Enter and confirm the **Broker Password** for the `operator` user of Apache Kafka.
2. If you enabled Kafka UI, enter and confirm the **Kafka UI Password**.

### Step 6: Feedback

Optional: answer the questions about your experience with Apache Kafka and your workload goals.

### Step 7: Review + submit

1. Check the configuration, the plan details, and the price.
2. Enter your **Name**, **Preferred e-mail address**, and **Preferred phone number**.
3. Under **Co-Admin Access Permission**, select **I agree to the terms and conditions above** to
   allow Canonical to manage the deployed resource groups. See
   [Shared responsibility](explanation-azure-managed-responsibility).
4. Click **Create**.

## Check the confirmation email

When the deployment completes, Canonical sends a follow-up email from the Managed Solutions Portal
with the connection details and instructions on how to get support. For what the connection details
include, see [Credentials](explanation-azure-managed-credentials).

(how-to-deploy-azure-managed-connect)=

## Connect a client

1. Save the CA certificates from the email to a file, for example `ca.pem`.

2. Create a `client.properties` file with the broker username from the email and the broker password
   you set:

   ```text
   security.protocol=SASL_SSL
   sasl.mechanism=SCRAM-SHA-512
   sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="<username>" password="<broker-password>";
   ssl.truststore.type=PEM
   ssl.truststore.location=ca.pem
   ```

3. List the topics to check the connection. Replace `<broker-endpoint>` with a broker endpoint from
   the email, including the port:

   ```shell
   kafka-topics.sh --list \
     --bootstrap-server <broker-endpoint> \
     --command-config client.properties
   ```

If you enabled Kafka UI, open its URL from the email and log in with the username from the email and
the password you set.
