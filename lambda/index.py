import json 
import boto3
import os 
from datetime import datetime
from botocore.config import Config

"""
MAIN PROCESSING LAMBDA - S3 Event Handler
=========================================
Purpose: Orchestrates the entire claims processing workflow
Triggers: S3 file uploads (documents and images)
Actions: 
- Differentiates between images and documents
- Invokes Bedrock Agent with structured prompts
- Handles retry logic and error recovery
- Coordinates all action groups for complete claim processing
"""


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
            'max_attempts': 3,  # Increased retry attempts since we're removing manual retry
            'mode': 'adaptive'  # Adaptive retry mode with exponential backoff
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
                - Ex.("The initial claim form provided details about a rear-end collision involving a 2023 Honda CR-V on 2025-05-18 in Boston, MA. The vehicle is covered under an active premium policy AUTO-5678-9012. However, the claim is being denied as it was filed 78 days after the incident, which is outside the 30-day window required for filing claims based on the policy guidelines." )

            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            CRITICAL: Extract the specific fields from the analyzeImage results and populate them in claim_details.
            Everything must be in proper JSON format!

            {{
                "claim_id": "[extract claim_id from image analysis results]",
                "claim_details": {{
                    "damage_description": "[extract damage_description from image analysis results]",
                    "damage_severity": "[extract severity from image analysis results as minor/moderate/severe]",
                    "affected_areas": ["[extract affected_areas from image analysis results]"],
                    "estimated_cost_from_image": "[extract estimated_cost from image analysis results]"
                }},
                "vehicle_info": {{
                    "make": "[if visible]",
                    "model": "[if visible]",
                    "year": "[if visible]"
                }},
                "documents": {{
                    "current_uploaded_documents": ["[list ALL uploaded files including {key}]"],
                    "required_documents": ["[from KB based on claim type]"]
                }},
                "version_summary": {{
                    "claim_status": "PENDING",
                    "document_analysis": "Detailed narrative of visible damage, vehicles, in paragraph form",
                    "document_uploaded": "{key}",
                    "next_steps": "the customer actions that are needed (what remaining docs)",
                    "remaining_requirements": ["[doc1]", "[doc2]"]
                }}
            }}

            NOTIFICATION
            -----------
            Use sendNotification operation with damage assessment and next steps.
            Start with "Dear Customer"
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
            4. Make sure to include a summary of what was found in the '{file_name}' in the document_analysis
                - Here is an example: ("The initial claim form provided details about a rear-end collision involving a 2023 Honda CR-V on 2025-05-18 in Boston, MA. The vehicle is covered under an active premium policy AUTO-5678-9012. However, the claim is being denied as it was filed 78 days after the incident, which is outside the 30-day window required for filing claims based on the policy guidelines.") )

            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            - Only include fields found in document. Do not include null/empty information in the table if not present!
            Everything must be in proper JSON format!
            

            {{
                "claim_id": "[extracted from document]",
                "claim_details": {{
                    "policy_number": "[if present]",
                    "customer_id": "[if present]",
                    "incident_date": "[if present]",
                    "incident_location": "[if present]",
                    "total_repair_cost": "[if present]",
                    "active_policy": "[true/false from KB]",
                    "reported_within_thirty_days": "[calculated true/false]",
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
                    "current_uploaded_documents": ["[list ALL uploaded files including {file_name}]"],
                    "required_documents": ["[from KB based on claim type]"]
                }},
                "version_summary": {{
                    "claim_status": "[APPROVED/PENDING/DENIED]",
                    "document_analysis": "[Thorough summary of findings, description of incident, overview of claim status]",
                    "document_uploaded": "{file_name}",
                    "next_steps": "[the customer actions that are needed, the remaining docs needed]",
                    "remaining_requirements": ["[doc1]", "[doc2]"]
                }}
            }}

            NOTIFICATION
            -----------
            Use sendNotification operation with status and next steps.
            Start with "Dear Customer"
            End with "Sincerely, AnyCompany Claims Department"
            """


        print(f"Using session state: {json.dumps(sessionState)}")
        print(f"Using input text: {inputText}")

        # Invoke the Bedrock agent - retries handled by boto3 config
        print("Starting agent invocation with timeout and retry configuration")
        print(f"DEBUG - Image file? {is_image_file(key)}")
        
        try:
            print("Invoking Bedrock agent with built-in retry logic")
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
            
            print("Agent invocation successful")
            
        except Exception as e:
            print(f"Agent invocation failed after all retries: {str(e)}")
            response_text = f"Error invoking agent: {str(e)}"
        
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