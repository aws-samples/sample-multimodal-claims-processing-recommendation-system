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
            - ALWAYS Use getClaimById operation
            - If exists: review history and uploaded documents
            - Note current status

            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            *IMPORTANT: All JSON fields must be properly quoted strings or valid JSON objects/arrays.

            claim_id: [required]
            claim_details: {{
                "damage_description": [visible damage details],
                "damage_severity": [minor/moderate/severe],
                "affected_areas": [damage locations],
                "estimated_cost_from_image": [if estimatable]
            }}

            documents: {{
                "current_uploaded_documents": ["{key}"],
                "required_documents": [based on claim type]
            }}

            version_summary: {{
                "claim_status": [based on ALL documents],
                "document_analysis": [detailed image analysis],
                "document_uploaded": "{key}",
                "next_steps": [customer actions needed],
                "remaining_requirements": [outstanding documentation]
            }}

            NOTIFICATION AND STATUS
            ---------------------
            1. Status Rules:
            - DENIED if:
                * Inconsistent damage
                * Inactive policy
            - PENDING if:
                * Missing documentation
            - APPROVED if:
                * All requirements met
                * Damage verified
                * Active policy

            2. Use sendNotification operation to send notification with:
            - Damage assessment
            - Current status
            - Required documents
            - Next steps
            - Payment/deductible (if APPROVED)

            CRITICAL REMINDERS
            ----------------
            - Include ONLY visible information
            - Review ALL previous documents
            - MAKE SURE TO format as proper JSON
            - Include '{key}' in uploads
            - Be specific about visible elements
            - Verify all requirements before approval
            - Include payment details for approved claims
            - In the notifications, end with "Sincerely, AnyCompany Claims Department"
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
            
            INITIAL DOCUMENT ANALYSIS
            ------------------------
            First, analyze '{file_name}' to extract any available information:
            - Claim ID (REQUIRED)
            - Policy number
            - Customer ID
            - Vehicle details (make/model/year/VIN)
            - Incident date and location
            - Incident description
            - Total repair cost
            
            VALIDATION CHECKS
            ------------------------------------------------
            1. Policy Status Check:
            - Query knowledge base with exact policy number
            - Confirm if status is 'ACTIVE'
            - Record exact policy status for document_analysis

            2. Timing Check:
            - Calculate days between incident_date and {today_date}
            - Verify if within 30-day window
            - Document calculation in analysis

            3. Existing Claim Check:
            - ALWAYS Use getClaimById operation
            - If exists: review history and uploaded documents
            - Note current status
            
            CLAIM PROCESSING
            ---------------
            Create claim ONCE with createClaim operation:
            * IMPORTANT: All JSON fields must be properly quoted strings or valid JSON objects/arrays.
            
            claim_id: [extracted ID]
            claim_details: {{
                "customer_id": [extracted],
                "policy_number": [extracted],
                "active_policy": [if policy is active],
                "reported_within_thirty_days": [true if the incident occurred within last 30 days],
                "claim_type": [determined from description and knowledge base, accident/theft],
                "incident_date": [extracted],
                "incident_location": [extracted],
                "total_repair_cost": [extracted]
                "coverage_type": [from knowledge base],
                "deductible": [from knowledge base],
            }},

            "vehicle_info": {{
                "make": [extracted],
                "model": [extracted], 
                "year": [extracted],
                "vin": [extracted]
            }},

            documents: {{
                "current_uploaded_documents": ["{file_name}"],
                "required_documents": [from knowledge base]
            }}
            version_summary: {{
                "claim_status": [determine based on ALL documents, not just this one],
                "document_analysis": [Thorough summary of findings, description of incident, overview of claim status],
                "document_uploaded": "{file_name}",
                "next_steps": [what customer needs to do],
                "remaining_requirements": [check what remaining uploads are necessary]
            }}
            
            NOTIFICATION AND STATUS
            ----------------------
            
            1. Status Rules:
            - DENIED if:
                * Inactive policy
                * Outside 30-day window
            - PENDING if:
                * Missing required documents
            - APPROVED if:
                * Active policy
                * All documents received
                * Within 30-day window

            2. Use sendNotification operation to send notification with:
            - Upload confirmation
            - Current status
            - Missing requirements
            - Next steps
            - Payment/deductible (if APPROVED)

            CRITICAL REMINDERS:
            ------------------
            - NEVER skip any validation step or the createClaim operation
            - Process ALL available information
            - Include '{file_name}' in uploaded documents
            - Review ALL previous documents for existing claims
            - MAKE SURE to Format all data as JSON
            - Double-check date calculations
            - For APPROVED claims, always include payment and deductible information in notifications
            - For DENIED claims, include the reason as to why the claim got denied, mention "Please contact AnyCompany at 1-800-CLAIMS for questions about this denial"
            - In the notifications, end with "Sincerely, AnyCompany Claims Department"
            
            """


        print(f"Using session state: {json.dumps(sessionState)}")
        print(f"Using input text: {inputText}")

        # Invoke the Bedrock agent with retry logic
        print("Starting agent invocation with timeout and retry configuration")
        print(f"DEBUG - Image file? {is_image_file(key)}")
        
        max_retries = 3
        retry_delay = 5  # seconds
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
                print(f"Error on attempt {retry_attempt + 1}/{max_retries}: {str(e)}")
                if retry_attempt < max_retries - 1:
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    # Increase delay for next retry (exponential backoff)
                    retry_delay *= 2
                else:
                    # Last attempt failed
                    print("All retry attempts failed")
                    response_text = f"Error after {max_retries} attempts: {str(e)}"
        
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