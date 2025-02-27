import Bedrock, Content, Prompt
import Similarity_Search as search
#import Retrieve_Data as retrieve
 
def get_output(data):
    #print("data we recived:", data)
    # Set data in Similarity_Search
    search.data = data
    results = search.get_results()  # Get the results from Similarity_Search
    print("Results retrieved using PGVector:\n",results)
   
    #print("\nResults retrieved using Langchain:")
    #retrieve.search(data)
    #print("\n")
 
    # Ensure results is a dictionary
    if not isinstance(results, dict):
        raise ValueError("Expected results to be a dictionary")
 
    result_salient = results.get('salient_features')
    result_history = results.get('history')
   
    #print("result salient:",result_salient)
    #print("result history:",result_history)
   
    # Check types of result_salient and result_history
    if not isinstance(result_salient, list) or not isinstance(result_history, list):
        raise ValueError("Expected salient_features and history to be lists")
 
    # Collect ancillaries
    ancillaries = [str(item.get('ancillary', '')) for item in result_history]
   
    #print("ancillaries:", ancillaries)
 
    # Generate content and prompt
    content = Content.get_content(result_history, result_salient)
    prompt = Prompt.get_prompt(content, result_salient, result_history, data, ancillaries)
   
    #print("prompt generated:",prompt)
    # Get recommendation
    response = Bedrock.get_recommendation(prompt, content)
    #print("response:",response)
 
    if response:
        # Debug the response structure
        try:
            output = response['output']['message']['content'][0]['text']
            return output
        except KeyError as e:
            raise ValueError(f"Unexpected response format: {e}")
   
    return None
