# lambda/send_notification.py
import json
import boto3
import os

"""
NOTIFICATION ACTION GROUP
========================
Purpose: Sends email notifications via SNS for claim status updates
Key Features:
- Customer communication for claim updates
- Status alerts and next steps guidance
- Automated email delivery through SNS
- Customizable subject and message content
"""


def extract_properties(event):
    """Extract properties from the event structure"""
    try:
        properties = event['requestBody']['content']['application/json']['properties']
        data = {}
        for prop in properties:
            data[prop['name']] = prop['value']
        return data
    except Exception as e:
        print(f"Error extracting properties: {str(e)}")
        return {}

def handler(event, context):
    """
    Lambda function to send notifications via SNS
    """
    print("=== SEND_NOTIFICATION ACTION GROUP START ===")
    print("Received event:", json.dumps(event, indent=2))
    
    try:
        # Extract action details
        action_group = event['actionGroup']
        api_path = event['apiPath']
        http_method = event['httpMethod']
        
        # Extract data from the event's properties
        data = extract_properties(event)
        subject = data.get('subject', 'Claim Update Notification')
        message = data.get('message', 'No message provided')
        
        # Get SNS topic ARN from environment variable
        topic_arn = os.environ.get('TOPIC_ARN')
        if not topic_arn:
            raise ValueError("Missing TOPIC_ARN environment variable")
        
        # Send notification
        sns = boto3.client('sns')
        response = sns.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message
        )
        
        print(f"Notification sent to {topic_arn}")
        
        # Prepare success response
        response_body = {
            'application/json': {
                'body': json.dumps({
                    'message': 'Notification sent successfully',
                    'messageId': response.get('MessageId', '')
                })
            }
        }
        
        # Create action response
        action_response = {
            'actionGroup': action_group,
            'apiPath': api_path,
            'httpMethod': http_method,
            'httpStatusCode': 200,
            'responseBody': response_body
        }
        
        # Print final response for debugging
        final_response = {
            'messageVersion': '1.0',
            'response': action_response,
            'sessionAttributes': event.get('sessionAttributes', {}),
            'promptSessionAttributes': event.get('promptSessionAttributes', {})
        }
        print("Final response from send_notifications:", json.dumps(final_response))
        print("=== SEND_NOTIFICATION ACTION GROUP END ===")
        
        # Return final response with required fields
        return final_response
            
    except Exception as e:
        print(f"Error sending notification: {str(e)}")
        error_response = {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': event.get('actionGroup', ''),
                'apiPath': event.get('apiPath', ''),
                'httpMethod': event.get('httpMethod', ''),
                'httpStatusCode': 500,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({
                            'message': f'Error sending notification: {str(e)}'
                        })
                    }
                }
            },
            'sessionAttributes': event.get('sessionAttributes', {}),
            'promptSessionAttributes': event.get('promptSessionAttributes', {})
        }
        return error_response
