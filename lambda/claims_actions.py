import json
import boto3
import os
from datetime import datetime
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
    print("=== CLAIMS_MANAGEMENT ACTION GROUP START ===")
    print("Received event:", json.dumps(event, indent=2))
    
    try:
        # Basic setup
        table_name = os.environ['TABLE_NAME']
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(table_name)
        
        # Extract data
        data = extract_properties(event)
        print("Extracted data:", json.dumps(data, default=decimal_default))
        
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
            if existing_claim:
                print(f"Found existing claim: {json.dumps(existing_claim, default=decimal_default)}")
                
                # Update previous version's is_latest flag
                table.update_item(
                    Key={
                        'claim_id': claim_id,
                        'version': existing_claim['version']
                    },
                    UpdateExpression='SET is_latest = :false',
                    ExpressionAttributeValues={
                        ':false': "false"
                    }
                )
        except Exception as e:
            print(f"Error checking for existing claim: {str(e)}")
            existing_claim = None
            
        # Create timestamp for version
        timestamp = datetime.now().isoformat()
        
      
        if existing_claim:
            # 1. Merge documents
            existing_docs = existing_claim.get('documents', {}).get('current_uploaded_documents', [])
            new_docs = data.get('documents', {}).get('current_uploaded_documents', [])
            merged_docs = list(set(existing_docs + new_docs))  # Remove duplicates
            
            # 2. Merge claim_details
            existing_details = existing_claim.get('claim_details', {})
            new_details = data.get('claim_details', {})

            # Define static fields that should only be updated if empty
            static_fields = {
                'policy_number',
                'customer_id',
                'coverage_amount',
                'deductible',
                'active_policy',
                'incident_date',
                'incident_location',
                'estimated_cost_from_image',  
                'total_repair_cost',           
                'claim_type'
            }

            # Convert any float values to Decimal
            def convert_to_decimal(details):
                converted = {}
                for k, v in details.items():
                    if isinstance(v, float):
                        converted[k] = Decimal(str(v))
                    else:
                        converted[k] = v
                return converted

            # Convert both existing and new details
            existing_details = convert_to_decimal(existing_details)
            new_details = convert_to_decimal(new_details)

            # Merge logic
            merged_details = existing_details.copy()

            for k, v in new_details.items():
                if v:  # Only if new value exists
                    if k in static_fields:
                        # Update static fields only if they don't exist or are empty
                        if not merged_details.get(k):
                            merged_details[k] = v
                    else:
                        # Always update dynamic fields
                        merged_details[k] = v
            
            # Update the item with merged data
            item = {
                'claim_id': claim_id,
                'version': timestamp,
                'is_latest': "true",
                'status': data.get('version_summary', {}).get('claim_status', 'PENDING'),
                'created_at': timestamp,
                
                # Use merged data
                'claim_details': merged_details,
                'documents': {
                    'current_uploaded_documents': merged_docs,
                    'required_documents': data.get('documents', {}).get('required_documents', [])
                },
                'version_summary': data.get('version_summary', {})
            }
        else:
            # New claim - use data as is
            item = {
                'claim_id': claim_id,
                'version': timestamp,
                'is_latest': "true",
                'status': data.get('version_summary', {}).get('claim_status', 'PENDING'),
                'created_at': timestamp,
                'claim_details': data.get('claim_details', {}),
                'documents': data.get('documents', {}),
                'version_summary': data.get('version_summary', {})
            }
        
        
        # Store in DynamoDB
        table.put_item(Item=item)
        
        # Prepare success response
        response_body = {
            'application/json': {
                'body': json.dumps({
                    'message': f'Claim {claim_id} created successfully',
                    'claim_id': claim_id,
                    'version': timestamp,
                    'claim_data': {
                        'status': item['status'],
                        'version_summary': item['version_summary'],
                        'claim_details': item['claim_details'],
                        'documents': item['documents']
                    }
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
        print("=== CLAIMS_MANAGEMENT ACTION GROUP END ===")
        
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
