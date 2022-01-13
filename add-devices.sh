#!/bin/bash

# Number of devices to provision
# NOTE : This script has been tested with 100 devices. More devices will require more resources (AKA bigger instance).
DEV_COUNT=20

# Path for storing device config
CUR_PATH=$(pwd)
DEV_PATH="${CUR_PATH}/devices"

# Some housekeeping
[ -d $DEV_PATH ] || mkdir $DEV_PATH
if [ -f device_list ]; then
    DEV_CNT_CHECK=$(cat device_list | wc -l)
    if [ $DEV_CNT_CHECK -ge 1 ]; then
        echo "Devices already added! Having issues? Try running 'bash cleanup.sh' before 'bash add-devices.sh'."
        exit 1
    fi
fi
echo -n > device_list

# Install dependencies
sudo yum install -y jq screen
pip3 install AWSIoTPythonSDK

# Create an IoT policy
# NOTE: This policy is for demostration purpose only! Please do not use in production environment.
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

# Create thing type
THING_TYPE_NAME=OilPumpV1
thing_type_test=$(aws iot describe-thing-type --thing-type-name $THING_TYPE_NAME > /dev/null)
if [ $? -ne 0 ]; then
    aws iot create-thing-type --thing-type-name $THING_TYPE_NAME
fi

# Create dynamic thing groups
aws iot create-dynamic-thing-group --thing-group-name "All" --query-string "thingName: oilpump-*" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "Atl" --query-string "shadow.reported.location:atl" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "Bos" --query-string "shadow.reported.location:bos" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "NYC" --query-string "shadow.reported.location:nyc" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "FWv0_1" --query-string "shadow.reported.firmware:0.1" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "FWv1_0" --query-string "shadow.reported.firmware:1.0" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "FWv1_5" --query-string "shadow.reported.firmware:1.5" > /dev/null
aws iot create-dynamic-thing-group --thing-group-name "FWv2_0" --query-string "shadow.reported.firmware:2.0" > /dev/null

echo "Starting device provisioning"
for i in $(seq 1 $DEV_COUNT); do
    # Setup device name and path
    THING_NAME=$(hexdump -n3 -e'/3 "oilpump-" 2/2 "%02X"' /dev/random)
    echo "Creating device #${i} with name ${THING_NAME}..."
    THING_PATH="$DEV_PATH/$THING_NAME"
    echo $THING_NAME >> device_list
    mkdir $THING_PATH
    # Create thing with attributes to thing
    aws iot create-thing --thing-name $THING_NAME --thing-type-name $THING_TYPE_NAME 2>&1 > $THING_PATH/thing_response
    # Create keys and certificate
    aws iot create-keys-and-certificate --set-as-active \
      --public-key-outfile $THING_PATH/public.key \
      --private-key-outfile $THING_PATH/private.key \
      --certificate-pem-outfile $THING_PATH/certificate.pem > $THING_PATH/keys_response
    ln -s "${CUR_PATH}/rootCA.pem" $THING_PATH/rootCA.pem
    # Parse output for certificate ARN and ID
    CERTIFICATE_ARN=$(jq -r ".certificateArn" $THING_PATH/keys_response)
    CERTIFICATE_ID=$(jq -r ".certificateId" $THING_PATH/keys_response)
    # Attach policy to certificate
    aws iot attach-policy --policy-name $POLICY_NAME --target $CERTIFICATE_ARN
    # Attach certificate to thing
    aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN
    # Run the iot_client.py script
    screen -dm -S "$THING_NAME" bash -c "source ~/.bash_profile; python3 iot_client.py --thing $THING_NAME --endpoint $IOT_ENDPOINT"
done

screen -ls
exit 0
