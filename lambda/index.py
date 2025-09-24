import json 
import boto3
import os 
from datetime import datetime
from botocore.config import Config
import time



def is_image_file(filename):
    """Check if file is an image based on extension"""
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif'}
    return any(filename.lower().endswith(ext) for ext in image_extensions)


def handler(event, context):
    # amazonq-ignore-next-line
    print('Received S3 event:', json.dumps(event))
    
    # Initialize clients with timeout and retry configuration
    region = os.environ.get('REGION', 'us-east-1')
    config = Config(
        connect_timeout=10,     # Connection timeout in seconds
        read_timeout=300,        # Read timeout in seconds
        retries={
            'max_attempts': 2,  # Number of retry attempts
            'mode': 'standard'  # Standard retry mode
        }
    )
    bedrock_agent = boto3.client('bedrock-agent-runtime', region_name=region, config=config)
    
    try:
        # Extract bucket and file information from the S3 event
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
        
        print(f"New file uploaded - Bucket: {bucket}, File: {key}")
        
        # Get the agent ID and alias ID from environment variables
        agent_id = os.environ.get('BEDROCK_AGENT_ID')
        agent_alias_id = os.environ.get('AGENT_ALIAS_ID')
        
        print(f"Using agent ID: {agent_id} and alias ID: {agent_alias_id}")
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        # Check if file is an image
        if is_image_file(key):
            print("Image file detected")
            # For images, no session state needed
            sessionState = {}
            inputText = f"""
            
            IMAGE ANALYSIS
            -------------
            Use analyzeImage operation for '{key}':
            - Claim ID extraction
            - Damage details and severity
            - Vehicle information
            - Damage locations and extent

            VALIDATIONS CHECK
            ----------------
            Existing Claim Check:
            - ALWAYS Use getClaimById operation to check for existing claims
                - If exists: review history of the claim and the uploaded documents. Understand the status of the claim
            - Note current status
            - Make sure to include a summary in the document_analysis 
                - Ex.("The initial claim form provided details about a rear-end collision involving a 2023 Honda CR-V on 2025-05-18 in Boston, MA. The vehicle is covered under an active premium policy AUTO-5678-9012. However, the claim is being denied as it was filed 78 days after the incident, which is outside the 30-day window required for filing claims based on the policy guidelines."
)

            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            Use information from image analysis action to perform the action.
            
            {{
                "claim_id": "[if visible in image]",
                "claim_details": {{
                    "damage_description": "[visible damage details]",
                    "damage_severity": "[minor/moderate/severe]",
                    "affected_areas": "[damage locations]",
                    "estimated_cost_from_image": [if estimatable]
                }},
                "vehicle_info": {{
                    "make": "[if visible]",
                    "model": "[if visible]",
                    "year": [if visible]
                }},
                "documents": {{
                    "current_uploaded_documents": [list all uploaded files including "{key}"],
                    "required_documents": [from KB, ALL the required documents needed based on claim type]
                }},
                "version_summary": {{
                    "claim_status": "PENDING",
                    "document_analysis": "Detailed narrative of visible damage, vehicles, in paragraph form ",
                    "document_uploaded": "{key}",
                    "next_steps": "the customer actions that are needed (what remaining docs)",
                    "remaining_requirements": [outstanding documents]
                }}
            }}

            NOTIFICATION
            -----------
            Use sendNotification operation with damage assessment and next steps.
            End with "Sincerely, AnyCompany Claims Department"
            """

        else:
            print("Document file detected")
            file_name = os.path.basename(key)
            # For documents, include session state and S3 URI
            s3_uri = f"s3://{bucket}/{key}"
            sessionState = {
                'files': [
                    {
                        'name': file_name,
                        'source': {
                            's3Location': {
                                'uri': s3_uri
                            },
                            'sourceType': 'S3'
                        },
                        'useCase': 'CODE_INTERPRETER'
                    }
                ]
            }
            inputText = f"""
            
            DOCUMENT ANALYSIS
            ----------------
            Analyze '{file_name}' to extract if present in document:
            - Claim ID (REQUIRED)
            - Policy number, Customer ID
            - Vehicle details (make/model/year/VIN)
            - Incident date and location
            - Total repair cost
            
            VALIDATION CHECKS
            ----------------
            1. Query knowledge base for policy status and coverage details if policy number is present in '{file_name}'
            2. Calculate days between incident_date and {today_date} (must be within 30 days)
            3. ALWAYS Use getClaimById operation to check for existing claims
                - If exists: review history of the claim and the uploaded documents. Understand the status of the claim
            5. Make sure to include a summary of what was found in the '{file_name}' in the document_analysis 
                - Here is an example: ("The initial claim form provided details about a rear-end collision involving a 2023 Honda CR-V on 2025-05-18 in Boston, MA. The vehicle is covered under an active premium policy AUTO-5678-9012. However, the claim is being denied as it was filed 78 days after the incident, which is outside the 30-day window required for filing claims based on the policy guidelines.")
)
           
            
            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            CRITICAL: Only include fields found in document. Do not include null/empty information in the table if not present!
            
            FORMATTING RULES:
            - Use proper array format: [item1, item2, item3] (with commas between items)
            - Keep string values intact (don't split on commas within values)
            - Use quotes for string values in arrays
            
            {{
                "claim_id": "[extracted from document]",
                "claim_details": {{
                    "policy_number": "[if present]",
                    "customer_id": "[if present]", 
                    "incident_date": "[if present]",
                    "incident_location": "[if present]",
                    "total_repair_cost": "[if present]",
                    "active_policy": [true/false from KB],
                    "reported_within_thirty_days": [calculated],
                    "claim_type": "[accident/theft]",
                    "coverage_type": "[from KB]",
                    "deductible": "[from KB]"
                }},
                "vehicle_info": {{
                    "make": "[if present]",
                    "model": "[if present]", 
                    "year": "[if present]",
                    "vin": "[if present]"
                }},
                "documents": {{
                    "current_uploaded_documents": ["{file_name}"],
                    "required_documents": [from KB, all the required docs needed based on the claim type]
                }},
                "version_summary": {{
                    "claim_status": "[APPROVED/PENDING/DENIED]",
                    "document_analysis": "[Comprehensive narrative of document contents and incident details and claim status in paragraph form]",
                    "document_uploaded": "{file_name}",
                    "next_steps": "[the customer actions that are needed, the remaining docs needed]",
                    "remaining_requirements": [outstanding documents]
                }}
            }}
            
            NOTIFICATION
            -----------
            Use sendNotification operation with status and next steps.
            End with "Sincerely, AnyCompany Claims Department"
            """


        print(f"Using session state: {json.dumps(sessionState)}")
        print(f"Using input text: {inputText}")

        # Invoke the Bedrock agent with retry logic
        print("Starting agent invocation with timeout and retry configuration")
        print(f"DEBUG - Image file? {is_image_file(key)}")
        
        max_retries = 2  # Reduced since Nova Pro has higher quotas
        base_delay = 5  # Reduced base delay
        max_delay = 60   # Reduced max delay (1 minute)
        response_text = ""
        
        for retry_attempt in range(max_retries):
            try:
                print(f"Attempt {retry_attempt + 1}/{max_retries} to invoke agent")
                agent_response = bedrock_agent.invoke_agent(
                    agentId=agent_id,
                    agentAliasId=agent_alias_id,
                    sessionId=context.aws_request_id,
                    inputText=inputText,
                    sessionState=sessionState
                )
                
                # Process the streaming response
                response_text = ""
                for event_chunk in agent_response['completion']:
                    if 'chunk' in event_chunk:
                        chunk = event_chunk['chunk']
                        if 'bytes' in chunk:
                            response_text += chunk['bytes'].decode('utf-8')
                
                # If we get here without exception, break out of retry loop
                print("Agent invocation successful")
                break
                
            except Exception as e:
                error_str = str(e)
                print(f"Error on attempt {retry_attempt + 1}/{max_retries}: {error_str}")
                
                # Check if it's a throttling error
                is_throttling = any(keyword in error_str.lower() for keyword in 
                                  ['throttling', 'rate exceeded', 'too many requests', 'service unavailable'])
                
                if retry_attempt < max_retries - 1:
                    if is_throttling:
                        # Throttling-specific delays: longer waits to respect quota limits
                        if retry_attempt == 0:
                            total_delay = 30  # First throttling retry: 30 seconds
                        else:
                            total_delay = 60  # Second throttling retry: 60 seconds
                        print(f"Throttling detected. Retrying in {total_delay} seconds to respect quota limits...")
                    else:
                        # Non-throttling errors: fast exponential backoff
                        delay = min(base_delay * (2 ** retry_attempt), max_delay)
                        # Add jitter (random component) to avoid thundering herd
                        import random
                        jitter = random.uniform(0.1, 0.3) * delay
                        total_delay = delay + jitter
                        print(f"Non-throttling error. Retrying in {total_delay:.2f} seconds...")
                    
                    time.sleep(total_delay)
                else:
                    # Last attempt failed
                    print("All retry attempts failed")
                    response_text = f"Error after {max_retries} attempts: {error_str}"
        
        print("Agent Response Text:", response_text)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'File processed by Bedrock agent',
                'file': key,
                'agent_response': response_text
            })
        }
        
    # amazonq-ignore-next-line
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        # Print the full stack trace for better debugging
        # amazonq-ignore-next-line
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }