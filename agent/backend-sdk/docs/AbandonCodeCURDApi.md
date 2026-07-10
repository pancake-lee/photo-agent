# swagger_client.AbandonCodeCURDApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**abandon_code_curd_add_abandon_code**](AbandonCodeCURDApi.md#abandon_code_curd_add_abandon_code) | **POST** /abandon-code | 
[**abandon_code_curd_del_abandon_code_by_idx1_list**](AbandonCodeCURDApi.md#abandon_code_curd_del_abandon_code_by_idx1_list) | **DELETE** /abandon-code | 
[**abandon_code_curd_get_abandon_code_list**](AbandonCodeCURDApi.md#abandon_code_curd_get_abandon_code_list) | **GET** /abandon-code | 
[**abandon_code_curd_update_abandon_code**](AbandonCodeCURDApi.md#abandon_code_curd_update_abandon_code) | **PATCH** /abandon-code | 

# **abandon_code_curd_add_abandon_code**
> ApiAddAbandonCodeResponse abandon_code_curd_add_abandon_code(body)



MARK REPEAT API START 一个表的接口定义  --------------------------------------------------  tbl : abandon_code

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.AbandonCodeCURDApi()
body = swagger_client.ApiAddAbandonCodeRequest() # ApiAddAbandonCodeRequest | 

try:
    api_response = api_instance.abandon_code_curd_add_abandon_code(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling AbandonCodeCURDApi->abandon_code_curd_add_abandon_code: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiAddAbandonCodeRequest**](ApiAddAbandonCodeRequest.md)|  | 

### Return type

[**ApiAddAbandonCodeResponse**](ApiAddAbandonCodeResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **abandon_code_curd_del_abandon_code_by_idx1_list**
> ApiEmpty abandon_code_curd_del_abandon_code_by_idx1_list(idx1_list=idx1_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.AbandonCodeCURDApi()
idx1_list = [56] # list[int] | MARK REPLACE PRIMARY IDX START (optional)

try:
    api_response = api_instance.abandon_code_curd_del_abandon_code_by_idx1_list(idx1_list=idx1_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling AbandonCodeCURDApi->abandon_code_curd_del_abandon_code_by_idx1_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **idx1_list** | [**list[int]**](int.md)| MARK REPLACE PRIMARY IDX START | [optional] 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **abandon_code_curd_get_abandon_code_list**
> ApiGetAbandonCodeListResponse abandon_code_curd_get_abandon_code_list(idx1_list=idx1_list, idx2_list=idx2_list, idx3_list=idx3_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.AbandonCodeCURDApi()
idx1_list = [56] # list[int] | MARK REPLACE IDX COL START 替换内容，索引字段 (optional)
idx2_list = [56] # list[int] |  (optional)
idx3_list = [56] # list[int] |  (optional)

try:
    api_response = api_instance.abandon_code_curd_get_abandon_code_list(idx1_list=idx1_list, idx2_list=idx2_list, idx3_list=idx3_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling AbandonCodeCURDApi->abandon_code_curd_get_abandon_code_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **idx1_list** | [**list[int]**](int.md)| MARK REPLACE IDX COL START 替换内容，索引字段 | [optional] 
 **idx2_list** | [**list[int]**](int.md)|  | [optional] 
 **idx3_list** | [**list[int]**](int.md)|  | [optional] 

### Return type

[**ApiGetAbandonCodeListResponse**](ApiGetAbandonCodeListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **abandon_code_curd_update_abandon_code**
> ApiUpdateAbandonCodeResponse abandon_code_curd_update_abandon_code(body)



MARK REMOVE IF NO PRIMARY KEY START

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.AbandonCodeCURDApi()
body = swagger_client.ApiUpdateAbandonCodeRequest() # ApiUpdateAbandonCodeRequest | 

try:
    api_response = api_instance.abandon_code_curd_update_abandon_code(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling AbandonCodeCURDApi->abandon_code_curd_update_abandon_code: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdateAbandonCodeRequest**](ApiUpdateAbandonCodeRequest.md)|  | 

### Return type

[**ApiUpdateAbandonCodeResponse**](ApiUpdateAbandonCodeResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

