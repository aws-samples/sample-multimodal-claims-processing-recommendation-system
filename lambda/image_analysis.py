import json 
import boto3
import base64
import os
from datetime import datetime 

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
    Lambda function to analyze images using Nova Pro 
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
        try:
            image_response = s3.get_object(
                Bucket=CLAIMS_BUCKET,
                Key=key
            )
            image_content = image_response['Body'].read()
            print(f"Image size: {len(image_content)} bytes")
            
            # Check if image is too large (Nova Pro has limits)
            if len(image_content) > 5 * 1024 * 1024:  # 5MB limit
                raise ValueError(f"Image too large: {len(image_content)} bytes. Max 5MB.")
            
            image_base64 = base64.b64encode(image_content).decode('utf-8')
            print(f"Base64 encoded image length: {len(image_base64)}")
            
        except Exception as s3_error:
            print(f"S3 error: {str(s3_error)}")
            raise
        
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
        
        # Determine image format from filename
        image_format = "jpeg"  # default
        if key.lower().endswith('.png'):
            image_format = "png"
        elif key.lower().endswith('.gif'):
            image_format = "gif"
        elif key.lower().endswith(('.webp', '.bmp')):
            image_format = "jpeg"  # Convert to jpeg for compatibility
        
        print(f"Using image format: {image_format}")
        
        # Nova Pro format - minimal parameters to avoid validation errors
        request_body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": image_format,
                                "source": {
                                    "bytes": image_base64
                                }
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        print(f"Sending request to Nova Pro with image format: {image_format}")
        
        try:
            response = bedrock.invoke_model(
                modelId='amazon.nova-pro-v1:0',
                body=json.dumps(request_body)
            )
            
            nova_response = json.loads(response['body'].read())
            print(f"Nova response structure: {list(nova_response.keys())}")
            print(f"Full Nova response: {json.dumps(nova_response, indent=2)}")
            
            # Handle different possible response structures
            if 'output' in nova_response and 'message' in nova_response['output']:
                analysis_results = nova_response['output']['message']['content'][0]['text']
            elif 'content' in nova_response:
                analysis_results = nova_response['content'][0]['text']
            elif 'completion' in nova_response:
                analysis_results = nova_response['completion']
            elif 'outputText' in nova_response:
                analysis_results = nova_response['outputText']
            else:
                # Fallback - try to find text in the response
                print(f"Unknown response structure, using full response: {nova_response}")
                analysis_results = str(nova_response)
                
        except Exception as bedrock_error:
            print(f"Bedrock error: {str(bedrock_error)}")
            print(f"Request body was: {json.dumps(request_body, indent=2)}")
            raise
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
        
        