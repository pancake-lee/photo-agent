# swagger_client.QueryServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**query_service_execute_sql**](QueryServiceApi.md#query_service_execute_sql) | **POST** /api/v1/sql/query | 
[**query_service_get_attribute_values**](QueryServiceApi.md#query_service_get_attribute_values) | **GET** /api/v1/sql/photos/attribute-values | 
[**query_service_get_photo_schema**](QueryServiceApi.md#query_service_get_photo_schema) | **GET** /api/v1/sql/photos/schema | 

# **query_service_execute_sql**
> ApiExecuteSQLResponse query_service_execute_sql(body)



执行 SELECT SQL 查询

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.QueryServiceApi()
body = swagger_client.ApiExecuteSQLRequest() # ApiExecuteSQLRequest | 

try:
    api_response = api_instance.query_service_execute_sql(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling QueryServiceApi->query_service_execute_sql: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiExecuteSQLRequest**](ApiExecuteSQLRequest.md)|  | 

### Return type

[**ApiExecuteSQLResponse**](ApiExecuteSQLResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **query_service_get_attribute_values**
> ApiGetAttributeValuesResponse query_service_get_attribute_values()



返回所有结构化属性的去重值（供 Text-to-SQL prompt 拼接）

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.QueryServiceApi()

try:
    api_response = api_instance.query_service_get_attribute_values()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling QueryServiceApi->query_service_get_attribute_values: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetAttributeValuesResponse**](ApiGetAttributeValuesResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **query_service_get_photo_schema**
> ApiGetPhotoSchemaResponse query_service_get_photo_schema()



返回 photos 表结构

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.QueryServiceApi()

try:
    api_response = api_instance.query_service_get_photo_schema()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling QueryServiceApi->query_service_get_photo_schema: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetPhotoSchemaResponse**](ApiGetPhotoSchemaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

