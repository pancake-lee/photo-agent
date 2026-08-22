# swagger_client.VlmServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**vlm_service_describe_photo**](VlmServiceApi.md#vlm_service_describe_photo) | **POST** /api/v1/photos/{id}/describe | 
[**vlm_service_get_describe_progress**](VlmServiceApi.md#vlm_service_get_describe_progress) | **GET** /api/v1/vlm/describe/progress | 
[**vlm_service_get_vlm_queue_status**](VlmServiceApi.md#vlm_service_get_vlm_queue_status) | **GET** /api/v1/vlm/queue/status | 
[**vlm_service_start_vlm_queue**](VlmServiceApi.md#vlm_service_start_vlm_queue) | **POST** /api/v1/vlm/queue/start | 
[**vlm_service_stop_vlm_queue**](VlmServiceApi.md#vlm_service_stop_vlm_queue) | **POST** /api/v1/vlm/queue/stop | 

# **vlm_service_describe_photo**
> ApiDescribePhotoResponse vlm_service_describe_photo(body, id)



单张照片触发 VLM 描述

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.VlmServiceApi()
body = swagger_client.ApiDescribePhotoRequest() # ApiDescribePhotoRequest | 
id = 'id_example' # str | 

try:
    api_response = api_instance.vlm_service_describe_photo(body, id)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling VlmServiceApi->vlm_service_describe_photo: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiDescribePhotoRequest**](ApiDescribePhotoRequest.md)|  | 
 **id** | **str**|  | 

### Return type

[**ApiDescribePhotoResponse**](ApiDescribePhotoResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **vlm_service_get_describe_progress**
> ApiGetDescribeProgressResponse vlm_service_get_describe_progress()



查询单张照片 VLM 描述进度

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.VlmServiceApi()

try:
    api_response = api_instance.vlm_service_get_describe_progress()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling VlmServiceApi->vlm_service_get_describe_progress: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetDescribeProgressResponse**](ApiGetDescribeProgressResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **vlm_service_get_vlm_queue_status**
> ApiGetVlmQueueStatusResponse vlm_service_get_vlm_queue_status()



查询 VLM 队列状态

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.VlmServiceApi()

try:
    api_response = api_instance.vlm_service_get_vlm_queue_status()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling VlmServiceApi->vlm_service_get_vlm_queue_status: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetVlmQueueStatusResponse**](ApiGetVlmQueueStatusResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **vlm_service_start_vlm_queue**
> ApiStartVlmQueueResponse vlm_service_start_vlm_queue(body)



启动 VLM 队列处理

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.VlmServiceApi()
body = swagger_client.ApiStartVlmQueueRequest() # ApiStartVlmQueueRequest | 

try:
    api_response = api_instance.vlm_service_start_vlm_queue(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling VlmServiceApi->vlm_service_start_vlm_queue: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiStartVlmQueueRequest**](ApiStartVlmQueueRequest.md)|  | 

### Return type

[**ApiStartVlmQueueResponse**](ApiStartVlmQueueResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **vlm_service_stop_vlm_queue**
> ApiStopVlmQueueResponse vlm_service_stop_vlm_queue(body)



中止 VLM 队列处理

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.VlmServiceApi()
body = swagger_client.ApiEmpty() # ApiEmpty | 

try:
    api_response = api_instance.vlm_service_stop_vlm_queue(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling VlmServiceApi->vlm_service_stop_vlm_queue: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiEmpty**](ApiEmpty.md)|  | 

### Return type

[**ApiStopVlmQueueResponse**](ApiStopVlmQueueResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

