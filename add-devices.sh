#!/bin/bash

# Number of devices to provision
# NOTE : This script has been tested with 100 devices. More devices will require more resources.
DEV_COUNT=10

# Path for storing device config
CUR_PATH=`pwd`
DEV_PATH="${CUR_PATH}/devices"

# Create an IoT policy
# NOTE: This policy is for demostration purpose only!
POLICY_NAME=FleetHubDemo_Policy
policy_name_test=$(aws iot list-policies | grep -c $POLICY_NAME)
if [ $policy_name_test -eq 0 ]; then
    aws iot create-policy --policy-name $POLICY_NAME --policy-document '{
    "Version":"2012-10-17",
    "Statement": [
        {
            "Effect":"Allow",
            "Action": "iot:*",
            "Resource":"*"
        }
    ]
}'
fi

# Get IoT Endpoint
IOT_ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS | jq -r ".endpointAddress")

# Get Root CA
wget https://www.amazontrust.com/repository/AmazonRootCA1.pem -O rootCA.pem

# Some housekeeping
[ -d $DEV_PATH ] || mkdir $DEV_PATH
echo -n > device_list

# Create thing type
THING_TYPE_NAME=OilPumpV1
thing_type_test=$(aws iot describe-thing-type --thing-type-name $THING_TYPE_NAME)
if [ $? -ne 0 ]; then
    aws iot create-thing-type --thing-type-name $THING_TYPE_NAME
fi

# Create dynamic thing groups
aws iot create-dynamic-thing-group --thing-group-name "All" --query-string "thingName: oilpump-*"
aws iot create-dynamic-thing-group --thing-group-name "Atl" --query-string "shadow.reported.location:atl"
aws iot create-dynamic-thing-group --thing-group-name "Bos" --query-string "shadow.reported.location:bos"
aws iot create-dynamic-thing-group --thing-group-name "NYC" --query-string "shadow.reported.location:nyc"
aws iot create-dynamic-thing-group --thing-group-name "FWv0_1" --query-string "shadow.reported.firmware:0.1"
aws iot create-dynamic-thing-group --thing-group-name "FWv1_0" --query-string "shadow.reported.firmware:1.0"
aws iot create-dynamic-thing-group --thing-group-name "FWv1_5" --query-string "shadow.reported.firmware:1.5"
aws iot create-dynamic-thing-group --thing-group-name "FWv2_0" --query-string "shadow.reported.firmware:2.0"

echo "Starting device provisioning"
for i in $(seq 1 $DEV_COUNT); do
    # Setup device name and path
    THING_NAME=$(hexdump -n3 -e'/3 "oilpump-" 2/2 "%02X"' /dev/random)

    echo "Creating device #${i} with name ${THING_NAME}..."
    THING_PATH="$DEV_PATH/$THING_NAME"
    echo $THING_NAME >> device_list
    mkdir $THING_PATH

    # Create thing with attributes to thing
    aws iot create-thing --thing-name $THING_NAME --thing-type-name $THING_TYPE_NAME > $THING_PATH/thing_response

    # Create keys and certificate
    aws iot create-keys-and-certificate --set-as-active \
      --public-key-outfile $THING_PATH/public.key \
      --private-key-outfile $THING_PATH/private.key \
      --certificate-pem-outfile $THING_PATH/certificate.pem > $THING_PATH/keys_response
    ln -s /home/ec2-user/workspace/rootCA.pem $THING_PATH/rootCA.pem

    # Parse output for certificate ARN and ID
    CERTIFICATE_ARN=$(jq -r ".certificateArn" $THING_PATH/keys_response)
    CERTIFICATE_ID=$(jq -r ".certificateId" $THING_PATH/keys_response)

    # Attach policy to certificate
    aws iot attach-policy --policy-name $POLICY_NAME --target $CERTIFICATE_ARN

    # Attach certificate to thing
    aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN

    echo -e "done!"
done

exit 0
