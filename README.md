# FSI Insurance IDP - Quest 2: Intelligent Claims Processing

This is a CDK Python project for building an intelligent claims processing system using AWS services.

## Project Overview

This project implements an intelligent document processing (IDP) solution for insurance claims using:
- AWS CDK for infrastructure as code
- AWS Bedrock for AI/ML capabilities
- Lambda functions for processing logic
- Knowledge base integration for enhanced processing

## Setup

The `cdk.json` file tells the CDK Toolkit how to execute your app.

This project is set up like a standard Python project. The initialization process creates a virtualenv within this project, stored under the `.venv` directory.

To manually create a virtualenv on MacOS and Linux:

```
$ python3 -m venv .venv
```

After the init process completes and the virtualenv is created, you can use the following step to activate your virtualenv.

```
$ source .venv/bin/activate
```

If you are a Windows platform, you would activate the virtualenv like this:

```
% .venv\Scripts\activate.bat
```

Once the virtualenv is activated, you can install the required dependencies.

```
$ pip install -r requirements.txt
```

At this point you can now synthesize the CloudFormation template for this code.

```
$ cdk synth
```

## Configuration

To receive email notifications, set your email address using CDK context:

```
$ cdk deploy -c notification_email=your-email@example.com
```

Or add it to `cdk.json`:

```json
{
  "context": {
    "notification_email": "your-email@example.com"
  }
}
```

## Testing

The `sample-claims/` folder contains sample documents for testing the end-to-end claims processing workflow. After deploying the stack, you can:

1. Upload documents from `sample-claims/` to the claims S3 bucket one at a time
2. Monitor the processing through CloudWatch logs
3. Check DynamoDB for processed claim records
4. Verify notifications are sent via SNS

## Useful commands

 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk docs`        open CDK documentation
