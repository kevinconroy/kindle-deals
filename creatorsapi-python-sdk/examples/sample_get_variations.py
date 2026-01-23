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
Sample script demonstrating how to use the CreatorsAPI Python SDK for GetVariations API
GetVariations operation retrieves variations of a product (like different colors, sizes, etc.)
along with detailed information including images, item info, offers, and other product data.
"""

import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from creatorsapi_python_sdk.api_client import ApiClient
from creatorsapi_python_sdk.api.default_api import DefaultApi
from creatorsapi_python_sdk.models.get_variations_request_content import GetVariationsRequestContent
from creatorsapi_python_sdk.exceptions import ApiException


def get_variations():
    """
    Sample function to demonstrate GetVariations API usage
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
    
    """ Specify ASIN """
    asin = "B0DLFMFBJW"
    
    """ Specify language of preference """
    """ For more details, refer https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/locale-reference"""
    languages_of_preference = ["en_US"]
    
    """ Choose resources you want from GetVariationsResource enum """
    """ For more details, refer: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/get-variations#resources-parameter """
    get_variations_resources = [
        'images.primary.medium',
        'itemInfo.title',
        'offersV2.listings.availability',
        'offersV2.listings.condition',
        'offersV2.listings.dealDetails',
        'offersV2.listings.isBuyBoxWinner',
        'offersV2.listings.loyaltyPoints',
        'offersV2.listings.merchantInfo',
        'offersV2.listings.price',
        'offersV2.listings.type',
        'variationSummary.variationDimension'
    ]

    # Create GetVariations request
    get_variations_request = GetVariationsRequestContent(
        partner_tag=partner_tag,
        asin=asin,
        languages_of_preference=languages_of_preference,
        resources=get_variations_resources
    )
    
    try:
        """ Sending request """
        response = api.get_variations(x_marketplace=marketplace, get_variations_request_content=get_variations_request)
        
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


get_variations()
