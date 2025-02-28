from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import psycopg2
import boto3
import requests
import json
import main as model

app = Flask(__name__)

def get_db_connection():
    try:
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name='us-west-2'
        )
        
        secret_name = "rds!db-7a18b7b9-0ae8-4955-a46d-33def5d7059b"
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
        secret = json.loads(get_secret_value_response['SecretString'])
   
        conn = psycopg2.connect(
            host='database-2.ctk2ke8se56b.us-west-2.rds.amazonaws.com',
            port='5432',
            database='postgres',
            user=secret['username'],
            password=secret['password']
        )
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        return None

def authenticate(username, password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM users WHERE username = %s AND password = %s",
                (username, password)
            )
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result is not None
        except Exception as e:
            print(f"Authentication error: {e}")
            return False
    return False

def save_rental_data(data, username):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO rental_only (
                    username,
                    pickup_location,
                    pickup_date,
                    pickup_time,
                    drop_off_location, 
                    drop_off_date,
                    drop_off_time,
                    age_verification,
                    country,
                    no_of_adults,
                    no_of_children,
                    vehicle_type,
                    preference,
                    output
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                username,
                data['pickup_location'],
                data['pickup_date'],
                data['pickup_time'],
                data['drop_off_location'],
                data['drop_off_date'],
                data['drop_off_time'],
                data['age_verification'],
                data['country'],
                data['no_of_adults'],
                data['no_of_children'],
                data['vehicle_type'],
                data['preference'],
                data.get('output', '')
            ))

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            return True

        except Exception as e:
            print(f"Database error: {str(e)}")
            if conn:
                conn.rollback()
            return False
    return False

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if authenticate(username, password):
        return jsonify({'success': True, 'message': 'Login successful'})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required'}), 400
        
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            cur.execute(
                "SELECT username FROM users WHERE username = %s",
                (username,)
            )
            if cur.fetchone():
                return jsonify({'success': False, 'message': 'Username already exists'}), 400
                
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, password)
            )
            conn.commit()
            cur.close()
            conn.close()
            
            return jsonify({'success': True, 'message': 'Account created successfully'})
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': False, 'message': 'Database connection failed'}), 500

@app.route('/rental/chat', methods=['POST'])
def rental_chat():
    data = request.get_json()
    prompt = data.get('prompt')
    username = data.get('username')
    
    if not prompt:
        return jsonify({'success': False, 'message': 'Prompt is required'}), 400        
    try:
        # Initialize CloudWatch client
        cloudwatch = boto3.client('cloudwatch', region_name='us-west-2')
        start_time = datetime.now()
        
        bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-west-2')      
        system_prompt = """You are a helpful car rental assistant. Extract rental information from the user's request and format it as JSON."""     
        claude_prompt = f"""Human: Extract and understand the following information from this car rental request, the age_verfication should return in 18+ or 25+ or 30+ or 45+ or 60+, the pickup_date and dropoff_date should return in YYYY-MM-DD format only, if the picup_location and dropoff_location has short form,spelling mistake then return with correct location, pickup_time and dropoff_time should return in Morning or Noon or Night based on request. Return only a JSON object with these fields:
        pickup_location, pickup_date, pickup_time, drop_off_location, drop_off_date, drop_off_time, age_verification, 
        country, no_of_adults, no_of_children, vehicle_type, preference
        Request: {prompt}
        Assistant: Here is the extracted information in JSON format:"""
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [{"role": "user", "content": claude_prompt}],
            "max_tokens": 1000,
            "temperature": 0,
            "top_p": 1
        })
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=body
        )        
        response_body = json.loads(response['body'].read())
        extracted_data = json.loads(response_body['content'][0]['text'])
        output = model.get_output(extracted_data)
        extracted_data['output'] = output
        
        # Calculate latency
        end_time = datetime.now()
        latency = (end_time - start_time).total_seconds() * 1000  # Convert to milliseconds
        
        # Log metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='BedrockMetrics',
            MetricData=[
                {
                    'MetricName': 'APILatency',
                    'Value': latency,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'SuccessfulRequests',
                    'Value': 1,
                    'Unit': 'Count'
                },
                {
                    'MetricName': 'TokensUsed',
                    'Value': len(prompt.split()),
                    'Unit': 'Count'
                }
            ]
        )
        
        if save_rental_data(extracted_data, username):
            print(f"Output: {output}")  # Log the output
            return jsonify({'success': True, 'output': output})
        return jsonify({'success': False, 'message': 'Failed to save rental data'}), 500
        
    except Exception as e:
        # Log error metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='BedrockMetrics',
            MetricData=[
                {
                    'MetricName': 'FailedRequests',
                    'Value': 1,
                    'Unit': 'Count'
                }
            ]
        )
        print(f"Error: {str(e)}")  # Log the error
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/rental/form', methods=['POST'])
def rental_form():
    data = request.get_json()
    username = data.get('username')
    
    if not username:
        return jsonify({'success': False, 'message': 'Username is required'}), 400

    # Initialize CloudWatch client
    cloudwatch = boto3.client('cloudwatch', region_name='us-west-2')
    start_time = datetime.now()

    required_fields = [
        'pickup_location', 'pickup_date', 'pickup_time',
        'age_verification', 'country', 'no_of_adults', 'vehicle_type'
    ]
    
    missing = [field for field in required_fields if not data.get(field)]
    
    if missing:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing)}'}), 400
        
    try:
        output = model.get_output(data)
        data['output'] = output

        # Calculate latency
        end_time = datetime.now()
        latency = (end_time - start_time).total_seconds() * 1000  # Convert to milliseconds
        
        # Log metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='RentalFormMetrics',
            MetricData=[
                {
                    'MetricName': 'FormProcessingLatency',
                    'Value': latency,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'SuccessfulFormSubmissions',
                    'Value': 1,
                    'Unit': 'Count'
                }
            ]
        )

        if save_rental_data(data, username):
            print(f"Output: {output}")  # Log the output
            return jsonify({'success': True, 'output': output})
        return jsonify({'success': False, 'message': 'Failed to save rental data'}), 500

    except Exception as e:
        # Log error metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='RentalFormMetrics',
            MetricData=[
                {
                    'MetricName': 'FailedFormSubmissions',
                    'Value': 1,
                    'Unit': 'Count'
                }
            ]
        )
        print(f"Error: {str(e)}")  # Log the error
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/rental/inventory-update', methods=['POST'])
def add_car():
    data = request.get_json()
    
    # Check required fields
    required_fields = [
        'car_code', 'type_of_car', 'car_model', 
        'ancillary_available', 'cost', 'capacity',
        'salient_features'
    ]
    
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing)}'}), 400

    # Generate car summary in required format
    car_summary = '{' + f'""CAR_ID"":"""",""CAR_CODE"":""{data["car_code"]}"",""TYPE_OF_CAR"":""{data["type_of_car"]}"",""CAR_MODEL"":""{data["car_model"]}"",""ANCILLARY_AVAILABLE"":""{data["ancillary_available"]}"",""COST"":""{str(data["cost"])}"",""CAPACITY"":""{str(data["capacity"])}"",""SALIENT_FEATURES"":""{data["salient_features"]}""' + '}'
        
    try:
        # Initialize S3 client
        s3 = boto3.client('s3')
        bucket = 'projectfileforbb'
        key = 'Cars_table 1.csv'
        
        try:
            # Try to download existing CSV
            response = s3.get_object(Bucket=bucket, Key=key)
            csv_content = response['Body'].read().decode('utf-8')
            
            # Get last car_id
            last_id = 1
            if csv_content:
                lines = csv_content.strip().split('\n')
                if len(lines) > 1:  # If there's data beyond header
                    last_id = int(lines[-1].split(',')[0]) + 1
                    
        except s3.exceptions.NoSuchKey:
            # If file doesn't exist, create header
            csv_content = "CAR_ID,CAR_CODE,TYPE_OF_CAR,CAR_MODEL,ANCILLARY_AVAILABLE,COST,CAPACITY,SALIENT_FEATURES,CAR_SUMMARY"
            last_id = 1

        # Update car_id in summary
        car_summary = car_summary.replace('""CAR_ID"":""""', f'""CAR_ID"":""{str(last_id)}""')
                
        # Format ancillary_available with quotes
        ancillary = f'"{data["ancillary_available"]}"'
                
        # Prepare new row
        new_row = f"\n{last_id},{data['car_code']},{data['type_of_car']},{data['car_model']},"
        new_row += f"{ancillary},{data['cost']},{data['capacity']},"
        new_row += f'"{data["salient_features"]}","{car_summary}"'
        
        # Append new row to CSV content
        updated_content = csv_content + new_row
        
        # Upload updated CSV back to S3
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=updated_content.encode('utf-8')
        )
        
        return jsonify({
            'success': True,
            'message': 'Car added successfully',
            'car_id': last_id
        })
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/rental/metrics', methods=['GET'])
def get_metrics():
    try:
        # Initialize CloudWatch client
        cloudwatch = boto3.client('cloudwatch', region_name='us-west-2')
        
        # Get current time and calculate time window using UTC
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=1)  # Last 24 hours
        
        # Get metrics for API latency
        latency_response = cloudwatch.get_metric_statistics(
            Namespace='BedrockMetrics',
            MetricName='APILatency',
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,  # 1 hour periods
            Statistics=['Average', 'Maximum']
        )
        
        # Get metrics for successful/failed requests
        success_response = cloudwatch.get_metric_statistics(
            Namespace='BedrockMetrics', 
            MetricName='SuccessfulRequests',
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Sum']
        )
        
        failed_response = cloudwatch.get_metric_statistics(
            Namespace='BedrockMetrics',
            MetricName='FailedRequests', 
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=['Sum']
        )
        
        # Format metrics data with default values if no datapoints
        metrics = {
            'latency': [
                {'Average': dp['Average'], 'Maximum': dp['Maximum']} for dp in latency_response.get('Datapoints', [])
            ],
            'requests': {
                'successful': [dp['Sum'] for dp in success_response.get('Datapoints', [])],
                'failed': [dp['Sum'] for dp in failed_response.get('Datapoints', [])]
            }
        }
        
        return jsonify({'success': True, 'metrics': metrics})
        
    except Exception as e:
        print(f"Error fetching metrics: {str(e)}")
        return jsonify({'success': False, 'message': 'Error fetching metrics', 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
