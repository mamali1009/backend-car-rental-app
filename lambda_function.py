# lambda_function.py
import aws_lambda_wsgi
from app import app

def lambda_handler(event, context):
    # Ensure 'queryStringParameters' exists in the event
    if 'queryStringParameters' not in event:
        event['queryStringParameters'] = None
    return aws_lambda_wsgi.response(app, event, context)
