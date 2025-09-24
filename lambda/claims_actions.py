import json
import boto3
import os
from datetime import datetime
from decimal import Decimal

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def parse_agent_object(value_str):
    """Parse agent-formatted object string like '{key=value, key2=value2}' to dict"""
    try:
        # First try standard JSON parsing
        return json.loads(value_str.strip())
    except json.JSONDecodeError:
        # Parse the agent's specific format
        try:
            content = value_str.strip().strip('{}')
            result = {}
            
            # The agent uses format like: key=value, key2=[item1, item2], key3=text with commas
            # We need to be very careful about comma splitting
            
            current_pos = 0
            while current_pos < len(content):
                # Find the next key
                equals_pos = content.find('=', current_pos)
                if equals_pos == -1:
                    break
                
                # Extract key (work backwards from = to find start)
                key_start = equals_pos - 1
                while key_start >= current_pos and content[key_start] not in ',':
                    key_start -= 1
                key_start += 1
                
                key = content[key_start:equals_pos].strip()
                
                # Find the value - this is tricky because values can contain commas
                value_start = equals_pos + 1
                
                # Look for the next key=value pattern to know where this value ends
                next_key_pos = len(content)  # Default to end of string
                
                # Search for next key pattern (word followed by =)
                search_pos = value_start + 1
                while search_pos < len(content):
                    if content[search_pos] == '=' and search_pos > value_start + 1:
                        # Found an equals, check if it's preceded by a key pattern
                        # Look backwards for comma + word
                        temp_pos = search_pos - 1
                        while temp_pos > value_start and content[temp_pos] not in ',':
                            temp_pos -= 1
                        
                        if temp_pos > value_start:  # Found a comma
                            potential_key = content[temp_pos + 1:search_pos].strip()
                            if potential_key.isalnum() or '_' in potential_key:
                                # This looks like a key, so the value ends at the comma
                                next_key_pos = temp_pos
                                break
                    search_pos += 1
                
                # Extract the value
                value = content[value_start:next_key_pos].strip()
                if value.endswith(','):
                    value = value[:-1].strip()
                
                # Process the value
                if value.startswith('[') and value.endswith(']'):
                    # Array - handle malformed arrays
                    array_content = value.strip('[]')
                    if array_content:
                        # Split by comma and clean up each item
                        items = []
                        for item in array_content.split(','):
                            item = item.strip().strip('"\'')
                            if item:
                                items.append(item)
                        result[key] = items
                    else:
                        result[key] = []
                elif value.lower() == 'true':
                    result[key] = True
                elif value.lower() == 'false':
                    result[key] = False
                elif value.lower() == 'null':
                    result[key] = None
                elif value.startswith('$'):
                    # Money value
                    result[key] = value.replace('$', '').replace(',', '')
                elif value.isdigit():
                    result[key] = value
                else:
                    # String value - keep as is
                    result[key] = value
                
                # Move to next position
                current_pos = next_key_pos + 1
            
            return result
            
        except Exception as e:
            print(f"Failed to parse agent format: {e}")
            print(f"Original value: {value_str}")
            return {}

def extract_properties(event):
    """Extract and parse properties from the event"""
    try:
        properties = event['requestBody']['content']['application/json']['properties']
        data = {}
        
        for prop in properties:
            name = prop['name']
            value = prop['value']
            prop_type = prop.get('type', 'string')
            
            print(f"Processing property {name} (type: {prop_type}): {value}")
            
            if prop_type == 'object':
                parsed_obj = parse_agent_object(value)
                data[name] = parsed_obj
                if not parsed_obj:
                    print(f"Failed to parse object for {name}: {value}")
            elif prop_type == 'array':
                try:
                    data[name] = json.loads(value.strip())
                except json.JSONDecodeError:
                    # Try parsing as agent format
                    if value.startswith('[') and value.endswith(']'):
                        content = value.strip('[]')
                        if content:
                            # Split by comma and clean up each item
                            items = []
                            for item in content.split(','):
                                item = item.strip().strip('"\'')
                                if item:
                                    items.append(item)
                            data[name] = items
                        else:
                            data[name] = []
                    else:
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
                # Vehicle fields moved to separate vehicle_info section
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
            
            # Merge vehicle info similarly
            existing_vehicle = existing_claim.get('vehicle_info', {})
            new_vehicle = data.get('vehicle_info', {})
            merged_vehicle = existing_vehicle.copy()
            
            # Vehicle fields are static - only update if empty
            for k, v in new_vehicle.items():
                if v and not merged_vehicle.get(k):
                    merged_vehicle[k] = v
            
            # Update the item with merged data
            item = {
                'claim_id': claim_id,
                'version': timestamp,
                'is_latest': "true",
                'status': data.get('version_summary', {}).get('claim_status', 'PENDING'),
                'created_at': timestamp,
                
                # Use merged data
                'claim_details': merged_details,
                'vehicle_info': merged_vehicle,  # New section
                'documents': {
                    'current_uploaded_documents': merged_docs,
                    'required_documents': data.get('documents', {}).get('required_documents', [])
                },
                'version_summary': data.get('version_summary', {})
            }
        else:
            # New claim - use data as is with new structure
            item = {
                'claim_id': claim_id,
                'version': timestamp,
                'is_latest': "true",
                'status': data.get('version_summary', {}).get('claim_status', 'PENDING'),
                'created_at': timestamp,
                'claim_details': data.get('claim_details', {}),
                'vehicle_info': data.get('vehicle_info', {}),  # New section
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
                        'vehicle_info': item['vehicle_info'],  # Include new section
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
