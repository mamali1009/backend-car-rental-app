import aws_lambda_wsgi
from app import app
import json

def lambda_handler(event, context):
    # Ensure 'queryStringParameters' exists in the event
    if 'queryStringParameters' not in event:
        event['queryStringParameters'] = None

    # Ensure 'httpMethod' exists in the event
    if 'httpMethod' not in event:
        return {
            'statusCode': 400,
            'body': json.dumps({'errorMessage': "KeyError: 'httpMethod' not found in event"})
        }

    return aws_lambda_wsgi.response(app, event, context)
