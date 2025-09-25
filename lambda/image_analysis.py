import json 
import boto3
import base64
import os
from datetime import datetime 

"""
IMAGE ANALYSIS ACTION GROUP
==========================
Purpose: AI-powered vehicle damage assessment using Claude 3.7 Sonnet
Key Features:
- Analyzes damage photos for severity and affected areas
- Provides repair cost estimates from visual assessment
- Extracts claim IDs and vehicle information from images
- Returns structured damage analysis for claim processing
"""


def extract_properties(event):
    """Extract and parse properties based on their declared types"""
    try:
        properties = event['requestBody']['content']['application/json']['properties']
        data = {}
        for prop in properties:
            name = prop['name']
            value = prop['value']
            prop_type = prop.get('type', 'string')

            # Handle different types appropriately
            if prop_type == 'array':
                # Try to parse as JSON array
                try:
                    # Remove any extra whitespace and newlines for arrays
                    cleaned_value = value.strip()
                    data[name] = json.loads(cleaned_value)
                except json.JSONDecodeError:
                    # If not valid JSON, treat as a single-item array
                    data[name] = [value]
            elif prop_type == 'object':
                # Try to parse as JSON object
                try:
                    # Remove any extra whitespace and newlines for objects
                    cleaned_value = value.strip()
                    data[name] = json.loads(cleaned_value)
                except json.JSONDecodeError:
                    # If not valid JSON, use as string
                    data[name] = value
            elif prop_type == 'number':
                try:
                    data[name] = float(value)
                except (ValueError, TypeError):
                    data[name] = 0
            elif prop_type == 'boolean':
                data[name] = value.lower() == 'true'
            else:  # string and other types
                data[name] = value
                
        return data
    except Exception as e:
        print(f"Error extracting properties: {str(e)}")
        return {}


def handler(event, context):
    """
    Lambda function to analyze images using claud sonnet 3 model
    """
    
    print("=== IMAGE_ANALYSIS ACTION GROUP START ===")
    print("Received event:", json.dumps(event))
    
    try:
        # Extract action details
        action_group = event['actionGroup']
        api_path = event['apiPath']
        http_method = event['httpMethod']
        
        # Get properties using our helper function
        data = extract_properties(event)
        image_file = data.get('image_file')
        # claim_id = data.get('claim_id')
        
        if not image_file:
            raise KeyError(f"Missing required fields. Got: {data}")
        
        print(f"Image path received: {image_file}")
        filename = image_file.split('/')[-1]
        key = filename
    
        # Get image from S3 using environment variable
        CLAIMS_BUCKET = os.environ['CLAIMS_BUCKET']
        s3 = boto3.client('s3')
        
        print(f"Getting image from bucket: {CLAIMS_BUCKET}, key: {key}")
        image_response = s3.get_object(
            Bucket=CLAIMS_BUCKET,
            Key=key
        )
        image_content = image_response['Body'].read()
        image_base64 = base64.b64encode(image_content).decode('utf-8')
        
        # Calling claud sonnet 3 model
        bedrock = boto3.client('bedrock-runtime')
        prompt = """
        Please analyze the provided image and provide:
        1. Detailed description of visible damage
        2. Severity assesssment (low, medium, high)
        3. List of affected vehicle areas 
        4. Estimated cost of repair from image
        5. Any additional notes or recommendations
        6. The claim ID in the image
        
        Format your response as JSON with these fields:
        - damage_description
        - severity
        - affected_areas (as array)
        - estimated_cost
        - notes
        - claim ID
        """
        
        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-3-7-sonnet-20250219-v1:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image',
                                'source': {
                                    'type': 'base64',
                                    'media_type': 'image/png',
                                    'data': image_base64
                                }
                            },
                            {
                                'type': 'text',
                                'text': prompt
                            }
                        ]
                    }
                ],
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 1000,
                'temperature': 0,
                'top_k': 250,
                'top_p': 1
            })
        )
        
        claude_response = json.loads(response['body'].read())
        analysis_results = claude_response['content'][0]['text']
        print(analysis_results)
        
        response_body = {
            'application/json': {
                'body': json.dumps({
                    'analysis_results': analysis_results
                })
            }
        }
        
        action_response = {
            'actionGroup': action_group,
            'apiPath': api_path,
            'httpMethod': http_method,
            'httpStatusCode': 200,
            'responseBody': response_body
        }
        
        final_response = {
            'messageVersion': '1.0',
            'response': action_response,
            'sessionAttributes': event.get('sessionAttributes', {}),
            'promptSessionAttributes': event.get('promptSessionAttributes', {})
        }
        print("Final response from image_analysis:", json.dumps(final_response))
        print("=== IMAGE_ANALYSIS ACTION GROUP END ===")
        return final_response
        
    except Exception as e:
        print(f"Error analyzing image: {str(e)}")
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
                            'message': f'Error analyzing image: {str(e)}'
                        })
                    }
                }
            },
            'sessionAttributes': event.get('sessionAttributes', {}),
            'promptSessionAttributes': event.get('promptSessionAttributes', {})
        }
        return error_response
        
        