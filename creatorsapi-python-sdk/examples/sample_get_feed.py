# coding: utf-8

"""
  Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.

  Licensed under the Apache License, Version 2.0 (the "License").
  You may not use this file except in compliance with the License.
  A copy of the License is located at

      http://www.apache.org/licenses/LICENSE-2.0

  or in the "license" file accompanying this file. This file is distributed
  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
  express or implied. See the License for the specific language governing
  permissions and limitations under the License.
"""

"""
Sample script demonstrating how to use the CreatorsAPI Python SDK
"""

import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from creatorsapi_python_sdk.api_client import ApiClient
from creatorsapi_python_sdk.api.default_api import DefaultApi
from creatorsapi_python_sdk.models.get_feed_request_content import GetFeedRequestContent
from creatorsapi_python_sdk.exceptions import ApiException


def get_feed():
    """
    Sample function to demonstrate GetFeed API usage
    """
    
    """ Please add your credentials """
    """ Please add your credential Id here """
    credential_id = "<YOUR CREDENTIAL ID>"
    
    """ Please add your credential secret here """
    credential_secret = "<YOUR CREDENTIAL SECRET>"

    """ Please add your credential version here """
    """ For eg- 2.1 for North America (NA) region """
    """ 2.2 for Europe (EU) region """
    """ 2.3 for Far East (FE) region """
    version = "<YOUR CREDENTIAL VERSION>"
    
    # Initialize API client
    api_client = ApiClient(
        credential_id=credential_id,
        credential_secret=credential_secret,
        version=version
    )
    
    # Initialize API
    api = DefaultApi(api_client)

    """ Forming request """
    """ Specify Feed name that your store has access to, Feed name can be found from list feeds api response """
    """ Eg- "us_standardized_apparel_retail.xml.gz" """
    feed_name = "us_standardized_apparel_retail.xml.gz"

    """
    Specify the marketplace to which you want to send the request
    Eg- "www.amazon.com" for US marketplace
    For more details, refer: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/common-request-headers-and-parameters#marketplace-locale-reference
    """
    marketplace = "<YOUR MARKETPLACE>"

    """ Forming request """
    try:
        get_feed_request = GetFeedRequestContent(feed_name=feed_name)
    except ValueError as exception:
        print("Error in forming Request: ", exception)
        return
        
    try:
        """ Sending request """
        response = api.get_feed(x_marketplace=marketplace, get_feed_request_content=get_feed_request)
        
        print('API called successfully.')
        print("Complete Response:\n", json.dumps(response.to_dict() if hasattr(response, 'to_dict') else str(response), indent=2))
        
    except ApiException as exception:
        print("Error calling Creators API!")
        print(exception)

    except TypeError as exception:
        print("TypeError:", exception)

    except ValueError as exception:
        print("ValueError:", exception)

    except Exception as exception:
        print("Unexpected error:", exception)


get_feed()
