import requests
import logging
import jwt
from urllib.parse import unquote

# https://sso.trocglobal.com/adfs/oauth2/authorize/?response_type=code&client_id=navigator_dev.adfs.client_id&resource=navigator_dev.adfs.identifier&redirect_uri=http%3A%2F%2Fnavigator.dev.mobileinsight.com%2Foauth2%2Fcallback&state=aHR0cHM6Ly9uYXZpZ2F0b3IuZGV2Lm1vYmlsZWluc2lnaHQuY29tL2hvbWUv&scope=openid
# http://navigator.dev.mobileinsight.com/oauth2/callback?code=aE5WadqvbEeRIxqdFGctRA.ghF0Hvj22QgiIiIj5GIz6tALTTo.c4eI6hbx0T9osGa1a-OJSvvtOO0jkcESxE9wHGrYQTkfqzVDPA-XeNsHkFv8wVFEHVskHklIcWcx5WyyXel0X6Xeh_AZURQeVIJzX-QWihuKePAZnQBJO52zLpcqM6Xwa0CGKo-b0tPtdOMxKFF6BxJxlIvgq5_2eifL0i0l30cCaNbCdRfL6qPOZHagZIIWmGfHotGHAW_qbYP-VSZpMNOzQk7y3_f13xKVp77wcJ7ud8NxlwWtZ8y_PnCEhPicDJZCJuLou7SPs6z1ETFKodl3J8WZnneV80QgH1K_BX7BnJUxeOPcGuRlddqe-c-weE2bnVxNUWrPiD826feIag&state=aHR0cHM6Ly9uYXZpZ2F0b3IuZGV2Lm1vYmlsZWluc2lnaHQuY29tL2hvbWUv&client-request-id=6ba756ee-7806-4cf1-ef00-0080010000dc

def start_auth():

def finish_auth():
    end_authorization_endpoint = "http://navigator.dev.mobileinsight.com/oauth2/callback"
    token_endpoint = "https://sso.trocglobal.com/adfs/oauth2/token"
    try:
        authorization_code = 'aE5WadqvbEeRIxqdFGctRA.ghF0Hvj22QgiIiIj5GIz6tALTTo.c4eI6hbx0T9osGa1a-OJSvvtOO0jkcESxE9wHGrYQTkfqzVDPA-XeNsHkFv8wVFEHVskHklIcWcx5WyyXel0X6Xeh_AZURQeVIJzX-QWihuKePAZnQBJO52zLpcqM6Xwa0CGKo-b0tPtdOMxKFF6BxJxlIvgq5_2eifL0i0l30cCaNbCdRfL6qPOZHagZIIWmGfHotGHAW_qbYP-VSZpMNOzQk7y3_f13xKVp77wcJ7ud8NxlwWtZ8y_PnCEhPicDJZCJuLou7SPs6z1ETFKodl3J8WZnneV80QgH1K_BX7BnJUxeOPcGuRlddqe-c-weE2bnVxNUWrPiD826feIag'
        state = 'aHR0cHM6Ly9uYXZpZ2F0b3IuZGV2Lm1vYmlsZWluc2lnaHQuY29tL2hvbWUv'
        request_id = '6ba756ee-7806-4cf1-ef00-0080010000dc'
    except Exception as err:
        print(err)
    print(authorization_code, state, request_id)
    logging.debug("Received authorization token: " + authorization_code)
    # getting an Access Token
    query_params = {
        "client_id": "navigator_dev.adfs.client_id",
        "grant_type": "authorization_code",
        "code": url = unquote(authorization_code).decode('utf8'),
        "redirect_uri": end_authorization_endpoint
    }
    query_params = requests.compat.urlencode(query_params)
    print(query_params)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        exchange = requests.post(
            token_endpoint,
            headers=headers,
            data=query_params
        )

        print(exchange, type(exchange))
        if exchange.status_code == 400:
            logging.error("ADFS server returned an error: " + exchange.json()["error_description"])
            # raise PermissionDenied

        if exchange.status_code != 200:
            logging.error("Unexpected ADFS response: " + exchange.content.decode())
            # raise PermissionDenied
        ## processing the exchange response:
        response = exchange.json()
        access_token = response["access_token"]
        token_type = response["token_type"] # ex: Bearer
        id_token = response["id_token"]
        logging.debug(f"Received access token: {access_token}")
        claims = jwt.decode(
            id_token,
            algorithms=['RS256', 'RS384', 'RS512'],
            verify=False
        )
        logging.debug(f"JWT claims:\n {claims}")
    except Exception as err:
        print(err)

if __name__ == '__main__':
    finish_auth()
