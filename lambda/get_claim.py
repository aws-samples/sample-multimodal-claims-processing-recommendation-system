import json
import boto3
import os
from decimal import Decimal

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def extract_properties(event):
    """Extract and parse properties from the event"""
    try:
        properties = event['requestBody']['content']['application/json']['properties']
        data = {}
        
        for prop in properties:
            name = prop['name']
            value = prop['value']
            prop_type = prop.get('type', 'string')
            
            if prop_type == 'object':
                try:
                    data[name] = json.loads(value.strip())
                except json.JSONDecodeError:
                    print(f"Failed to parse JSON for {name}")
                    data[name] = {}
            elif prop_type == 'array':
                try:
                    data[name] = json.loads(value.strip())
                except json.JSONDecodeError:
                    data[name] = []
            elif prop_type == 'number':
                try:
                    data[name] = Decimal(str(value))
                except:
                    data[name] = Decimal('0')
            else:  # string and other types
                data[name] = value
                
        return data
    except Exception as e:
        print(f"Error extracting properties: {str(e)}")
        return {}

def handler(event, context):
    print("=== GET_CLAIM ACTION GROUP START ===")
    print("Received event:", json.dumps(event, indent=2))
    
    try:
        # Basic setup
        table_name = os.environ['TABLE_NAME']
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        # Extract data
        data = extract_properties(event)
        print("Extracted data:", json.dumps(data))
        
        claim_id = data.get('claim_id')
        if not claim_id:
            raise KeyError("Missing required claim_id field")
        
        # Check for existing claim (get latest version)
        try:
            response = table.query(
                KeyConditionExpression='claim_id = :id',
                FilterExpression='is_latest = :true',
                ExpressionAttributeValues={
                    ':id': claim_id,
                    ':true': "true"
                }
            )
            existing_claim = response['Items'][0] if response.get('Items') else None
        except Exception as e:
            print(f"Error checking for existing claim: {str(e)}")
            existing_claim = None
        
        # Fetch all versions of the claim
        all_versions = []
        if claim_id:
            try:
                all_versions_response = table.query(
                    KeyConditionExpression='claim_id = :id',
                    ExpressionAttributeValues={
                        ':id': claim_id
                    }
                )
                all_versions = all_versions_response.get('Items', [])
                print(f"Found {len(all_versions)} versions for claim {claim_id}")
            except Exception as e:
                print(f"Error fetching all versions: {str(e)}")
        
        # Prepare response
        if existing_claim:
            response_body = {
                'application/json': {
                    'body': json.dumps({
                        'message': f'Claim {claim_id} found',
                        'claim_exists': True,
                        'claim_id': claim_id,
                        'claim_data': {
                            'status': existing_claim.get('status'),
                            'version_summary': existing_claim.get('version_summary', {}),
                            'claim_details': existing_claim.get('claim_details', {}),
                            'documents': existing_claim.get('documents', {})
                        },
                        'claim_history': [
                            {
                                'version': v.get('version'),
                                'version_summary': v.get('version_summary', {}),
                                'documents': v.get('documents', {}).get('current_uploaded_documents', [])
                            } for v in all_versions if v.get('version') != existing_claim.get('version')
                        ]
                    }, default=decimal_default)
                }
            }
        else:
            response_body = {
                'application/json': {
                    'body': json.dumps({
                        'message': f'Claim {claim_id} not found',
                        'claim_exists': False,
                        'claim_id': claim_id
                    }, default=decimal_default)
                }
            }
        
        # Create action response
        action_response = {
            'actionGroup': event['actionGroup'],
            'apiPath': event['apiPath'],
            'httpMethod': event['httpMethod'],
            'httpStatusCode': 200,
            'responseBody': response_body
        }
        
        final_response = {
            'messageVersion': '1.0',
            'response': action_response,
            'sessionAttributes': event.get('sessionAttributes', {}),
            'promptSessionAttributes': event.get('promptSessionAttributes', {})
        }
        
        print("Final response:", json.dumps(final_response, default=decimal_default))
        print("=== GET_CLAIM ACTION GROUP END ===")
        
        return final_response
        
    except Exception as e:
        print(f"Error: {str(e)}")
        error_response = {
            'messageVersion': '1.0',
            'response': {
                'httpStatusCode': 500,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({
                            'error': str(e)
                        })
                    }
                }
            }
        }
        return error_response
