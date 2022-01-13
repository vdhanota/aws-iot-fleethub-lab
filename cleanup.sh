#!/bin/bash
# Cleanup
CUR_PATH=$(pwd)
DEV_PATH="${CUR_PATH}/devices"
THING_TYPE_NAME=OilPumpV1
POLICY_NAME=FleetHubDemo_Policy
screen -ls | grep '(Detached)' | awk '{print $1}' | xargs -I % -t screen -X -S % quit

cat device_list | while read THING_NAME; do
    echo "Removing device ${THING_NAME}..."
    THING_PATH="$DEV_PATH/$THING_NAME"
    if [ -d $DEV_PATH ]; then
        CERTIFICATE_ARN=$(jq -r ".certificateArn" $THING_PATH/keys_response)
        CERTIFICATE_ID=$(jq -r ".certificateId" $THING_PATH/keys_response)
        aws iot detach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN
        aws iot detach-policy --policy-name $POLICY_NAME --target $CERTIFICATE_ARN
        aws iot update-certificate --certificate-id $CERTIFICATE_ID --new-status INACTIVE
        aws iot delete-certificate --certificate-id $CERTIFICATE_ID
        aws iot delete-thing --thing-name $THING_NAME
    fi
done

aws iot delete-dynamic-thing-group --thing-group-name "All" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "Atl" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "Bos" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "NYC" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "FWv0_1" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "FWv1_0" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "FWv1_5" > /dev/null
aws iot delete-dynamic-thing-group --thing-group-name "FWv2_0" > /dev/null
#aws iot deprecate-thing-type --thing-type-name $THING_TYPE_NAME
aws iot delete-policy --policy-name $POLICY_NAME

screen -wipe > /dev/null
rm -Rf $DEV_PATH
echo -n > device_list

exit 0
