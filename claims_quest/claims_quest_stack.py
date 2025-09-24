from aws_cdk import (
    Stack,
    RemovalPolicy, 
    aws_s3 as s3,
    aws_dynamodb as dynamo, 
    aws_lambda as _lambda,
    aws_sns as sns, 
    aws_s3_notifications as s3n,
    aws_s3_deployment as s3deploy,
    aws_iam as iam,
    aws_bedrock as bedrock,
    CfnOutput,
    Duration
)
from constructs import Construct
from cdklabs.generative_ai_cdk_constructs import (
    bedrock
)

class ClaimsQuestStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1 - Creating an S3 bucket for storing claim documents
        claims_bucket = s3.Bucket(
            self, 
            "ClaimsBucket",
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        
        # 2 - S3 bucket for knowledge base
        knowledge_base_bucket = s3.Bucket(
            self,
            "KnowledgeBaseBucket",
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        
        # Automatic deployment of knowledge base files
        s3deploy.BucketDeployment(
            self,
            "DeployKnowledgeBase",
            sources=[s3deploy.Source.asset("./knowledge-base")],
            destination_bucket=knowledge_base_bucket,
        )
        
        # 3 - Creating a DynamoDB table for storing claim details
        claims_table = dynamo.Table(
            self,
            "ClaimsTable",
            partition_key=dynamo.Attribute(
                name="claim_id", 
                type=dynamo.AttributeType.STRING
            ),
            sort_key=dynamo.Attribute(  
                name="version",
                type=dynamo.AttributeType.STRING
            ),
            billing_mode=dynamo.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        
        # Add GSI for querying latest versions
        claims_table.add_global_secondary_index(
            index_name="LatestVersionIndex",
            partition_key=dynamo.Attribute(
                name="claim_id", 
                type=dynamo.AttributeType.STRING
            ),
            sort_key=dynamo.Attribute(
                name="is_latest",
                type=dynamo.AttributeType.STRING
            ),
            projection_type=dynamo.ProjectionType.ALL
        )
        
        # 4 - SNS Topic for notifications
        claims_topic = sns.Topic(
            self,
            "ClaimsTopic",
            display_name="Claims Processing Notifications"
        )
        
        # Email subscription
        subscription = sns.Subscription(
            self, 
            "EmailSubscription",
            topic=claims_topic,  # Topic parameter IS required here
            protocol=sns.SubscriptionProtocol.EMAIL,
            endpoint="tirharsh@amazon.com"
        )


        # 5 - Creating Knowledge base
        claims_kb = bedrock.VectorKnowledgeBase(
            self, 
            'ClaimsKnowledgeBase',
            embeddings_model=bedrock.BedrockFoundationModel.TITAN_EMBED_TEXT_V1,
            instruction='Use this knowledge base to process and evaluate vehicle insurance claims based on company policies and guidelines.'
        )

        # Connect Knowledge Base to S3
        bedrock.S3DataSource(
            self, 
            'ClaimsDataSource',
            bucket=knowledge_base_bucket,  # This uses the existing knowledge_base_bucket
            knowledge_base=claims_kb,
            data_source_name='insurance-guidelines',
            chunking_strategy=bedrock.ChunkingStrategy.FIXED_SIZE,
        )
        
        # lambda function for action group - creating claims 
        claims_action_function = _lambda.Function(
            self,
            "ClaimsActionFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="claims_actions.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            environment={
                "TABLE_NAME": claims_table.table_name,  # Using your existing DynamoDB table
            }
        ) 
        # Grant DynamoDB permissions to the new Lambda
        claims_table.grant_read_write_data(claims_action_function)


        
        # lambda function for action group - image analysis
        image_analysis_function = _lambda.Function(
            self,
            "ImageAnalysisFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="image_analysis.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            environment={
                "CLAIMS_BUCKET": claims_bucket.bucket_name, 
                "TABLE_NAME": claims_table.table_name
            }
        )
        # Grant DynamoDB permissions
        claims_table.grant_read_write_data(image_analysis_function)
        # Grant S3 permissions to the new Lambda
        claims_bucket.grant_read(image_analysis_function)
        # Grant bedrock permissions
        image_analysis_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["*"]
            )
        )
        
        # lambda function for action group - sending notifications
        notification_function = _lambda.Function(
            self,
            "NotificationFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="send_notifications.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            environment={
                "TOPIC_ARN": claims_topic.topic_arn
            }
        )
        
        # Grant SNS permissions to the new Lambda
        claims_topic.grant_publish(notification_function)
        
        # Create Lambda function for get-claim action group
        get_claim_function = _lambda.Function(
            self,
            "GetClaimFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="get_claim.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(5),
            environment={
                "TABLE_NAME": claims_table.table_name
            }
        )
        
        # Grant dynamoDB read permissions
        claims_table.grant_read_data(get_claim_function)
        
        
        # Creating agent IAM role with managed Bedrock policy
        agent_role = iam.Role(
            self, 
            "BedrockAgentRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
            ],
            inline_policies={
                "AgentPolicy": iam.PolicyDocument(
                    statements=[
                        # Knowledge Base access
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "bedrock:Retrieve",
                                "bedrock:RetrieveAndGenerate"
                            ],
                            resources=[
                                claims_kb.knowledge_base_arn  # Get ARN from knowledge base
                            ]
                        ),
                        # S3 access
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "s3:GetObject",
                                "s3:ListBucket"
                            ],
                            resources=[
                                claims_bucket.bucket_arn,
                                f"{claims_bucket.bucket_arn}/*"
                            ]
                        ),
                        # Lambda access
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=["lambda:InvokeFunction"],
                            resources=[
                                claims_action_function.function_arn,
                                image_analysis_function.function_arn,
                                notification_function.function_arn,
                                get_claim_function.function_arn 
                                ]
                        )
                    ]
                )
            }
        )
        
        # Simple action group to create dynamo entry 
        claims_action_group = bedrock.AgentActionGroup(
            name="Claims_management",
            description="Action group for managing claims in DynamoDB",
            executor= bedrock.ActionGroupExecutor.fromlambda_function(claims_action_function),
            enabled=True,
            api_schema=bedrock.ApiSchema.from_local_asset("action_groups/create_claims/schema.json")
        )
        
        # Simple action group to analyze images
        image_analysis_action_group = bedrock.AgentActionGroup(
            name="Image_analysis",
            description="Analyze vehicle damage images",
            executor= bedrock.ActionGroupExecutor.fromlambda_function(image_analysis_function),
            enabled=True,
            api_schema=bedrock.ApiSchema.from_local_asset("action_groups/image_analysis/schema.json")
        )
        
        # Simple action group to send notifications
        notification_action_group = bedrock.AgentActionGroup(
            name="Send_notification",
            description="Send notifications about claim updates",
            executor= bedrock.ActionGroupExecutor.fromlambda_function(notification_function),
            enabled=True,
            api_schema=bedrock.ApiSchema.from_local_asset("action_groups/notifications/schema.json")
        )
        
        get_claim_action_group = bedrock.AgentActionGroup(
            name="Get_claim",
            description="Get claim details",
            executor= bedrock.ActionGroupExecutor.fromlambda_function(get_claim_function),
            enabled=True,
            api_schema=bedrock.ApiSchema.from_local_asset("action_groups/get_claim/schema.json")
        )
        
        # 6 - Create Bedrock Agent
        claims_agent = bedrock.Agent(
        self,
        "ClaimsProcessingAgent",
        foundation_model=bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_SONNET_V1_0,
        instruction="""You are an auto insurance claims processing assistant. 

        Query the knowledge base for policy validation and coverage details.

        Follow the specific instructions provided in each request exactly as given.""",
        
        should_prepare_agent=True,
        code_interpreter_enabled = True,
        existing_role=agent_role
        )

        claims_agent.add_knowledge_base(claims_kb)
        
        # Add action group to agent
        claims_agent.add_action_group(claims_action_group)
        claims_agent.add_action_group(image_analysis_action_group)
        claims_agent.add_action_group(notification_action_group)
        claims_agent.add_action_group(get_claim_action_group)
   
        agent_alias_test3 = bedrock.AgentAlias(self, 'agentaliastest3',
        alias_name='myalias3',
        agent = claims_agent,
        description='Working end-to-end!! - back to original'
    )


        # 7 - Lambda function
        processing_function = _lambda.Function(
            self,
            "ProcessingFunction",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="index.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.minutes(15),
            memory_size = 10240,
            environment={
                "CLAIMS_BUCKET": claims_bucket.bucket_name,
                "KB_BUCKET": knowledge_base_bucket.bucket_name,
                "TABLE_NAME": claims_table.table_name,
                "TOPIC_ARN": claims_topic.topic_arn,
                "KNOWLEDGE_BASE_ID": claims_kb.knowledge_base_id,
                "REGION": self.region,
                "BEDROCK_AGENT_ID": claims_agent.agent_id,
                "AGENT_ALIAS_ID": agent_alias_test3.alias_id
            },
        )
    
        # Granting permissions
        claims_bucket.grant_read_write(processing_function)
        claims_table.grant_read_write_data(processing_function)
        knowledge_base_bucket.grant_read(processing_function)
        claims_topic.grant_publish(processing_function)
        
        # Add Bedrock permissions to Lambda
        processing_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeAgent",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:Query"
                ],
                resources=["*"]
            )
        )
        

        
        # S3 event notification
        claims_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(processing_function)
        )

        # Adding CloudFormation outputs for easy reference
        CfnOutput(
            self, "ClaimsBucketName",
            value=claims_bucket.bucket_name,
            description="Name of the S3 bucket for claims uploads"
        )

        CfnOutput(
            self, "KnowledgeBaseBucketName",
            value=knowledge_base_bucket.bucket_name,
            description="Name of the S3 bucket for knowledge base content"
        )

        CfnOutput(
            self, "ClaimsTableName",
            value=claims_table.table_name,
            description="Name of the DynamoDB table for claims data"
        )

        CfnOutput(
            self, "ClaimsTopicArn",
            value=claims_topic.topic_arn,
            description="ARN of the SNS topic for claims notifications"
        )
        
        
        CfnOutput(
            self, "AgentId",
            value=claims_agent.agent_id,
            description="ID of the Bedrock agent"
        )
        
        CfnOutput(
            self, "AgentAliasId",
            value=agent_alias_test3.alias_id,
            description="ID of the Bedrock agent alias"
        )
        
        CfnOutput(
            self, "KnowledgeBaseArn",
            value=claims_kb.knowledge_base_arn,
            description="ARN of the knowledge base"
        )

        CfnOutput(
            self, "ClaimsBucketArn",
            value=claims_bucket.bucket_arn,
            description="ARN of the claims bucket"
        )
        
    