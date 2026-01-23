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
Sample script demonstrating how to use the CreatorsAPI Python SDK for SearchItems API
SearchItems operation searches for products on Amazon based on keywords and returns
detailed information including images, item info, offers, and other product data.
"""

import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from creatorsapi_python_sdk.api_client import ApiClient
from creatorsapi_python_sdk.api.default_api import DefaultApi
from creatorsapi_python_sdk.models.search_items_request_content import SearchItemsRequestContent
from creatorsapi_python_sdk.exceptions import ApiException


def search_items():
    """
    Sample function to demonstrate SearchItems API usage
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

    """
    Specify the marketplace to which you want to send the request
    Eg- "www.amazon.com" for US marketplace
    For more details, refer: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/common-request-headers-and-parameters#marketplace-locale-reference
    """
    marketplace = "<YOUR MARKETPLACE>"
    
    """ Please add your partner tag (store/tracking id) here """
    partner_tag = "<YOUR PARTNER TAG>"
    
    """ Specify keywords """
    keywords = "Harry Potter"
    
    """ Specify search index """
    search_index = "Books"
    
    """ Specify item count """
    item_count = 2
    
    """ Choose resources you want from SearchItemsResource enum """
    """ For more details, refer: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/search-items#resources-parameter """
    search_items_resources = [
        'images.primary.medium',
        'itemInfo.title',
        'offersV2.listings.availability',
        'offersV2.listings.condition',
        'offersV2.listings.dealDetails',
        'offersV2.listings.isBuyBoxWinner',
        'offersV2.listings.loyaltyPoints',
        'offersV2.listings.merchantInfo',
        'offersV2.listings.price',
        'offersV2.listings.type'
    ]
    
    # Create SearchItems request
    search_items_request = SearchItemsRequestContent(
        partner_tag=partner_tag,
        keywords=keywords,
        search_index=search_index,
        item_count=item_count,
        resources=search_items_resources
    )
    
    try:
        """ Sending request """
        response = api.search_items(x_marketplace=marketplace, search_items_request_content=search_items_request)
        
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


search_items()
