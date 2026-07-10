# swagger_client.TagServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**tag_service_bind_tags**](TagServiceApi.md#tag_service_bind_tags) | **POST** /api/v1/tags/bind | 
[**tag_service_get_photos_by_tag**](TagServiceApi.md#tag_service_get_photos_by_tag) | **GET** /api/v1/tags/{name}/photos | 
[**tag_service_list_tags**](TagServiceApi.md#tag_service_list_tags) | **GET** /api/v1/tags | 
[**tag_service_unbind_tags**](TagServiceApi.md#tag_service_unbind_tags) | **POST** /api/v1/tags/unbind | 

# **tag_service_bind_tags**
> ApiBindTagsResponse tag_service_bind_tags(body)



批量给照片绑定标签

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TagServiceApi()
body = swagger_client.ApiBindTagsRequest() # ApiBindTagsRequest | 

try:
    api_response = api_instance.tag_service_bind_tags(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TagServiceApi->tag_service_bind_tags: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiBindTagsRequest**](ApiBindTagsRequest.md)|  | 

### Return type

[**ApiBindTagsResponse**](ApiBindTagsResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **tag_service_get_photos_by_tag**
> ApiGetPhotosByTagResponse tag_service_get_photos_by_tag(name)



某标签下的照片

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TagServiceApi()
name = 'name_example' # str | 

try:
    api_response = api_instance.tag_service_get_photos_by_tag(name)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TagServiceApi->tag_service_get_photos_by_tag: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **name** | **str**|  | 

### Return type

[**ApiGetPhotosByTagResponse**](ApiGetPhotosByTagResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **tag_service_list_tags**
> ApiListTagsResponse tag_service_list_tags()



所有标签列表

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TagServiceApi()

try:
    api_response = api_instance.tag_service_list_tags()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TagServiceApi->tag_service_list_tags: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiListTagsResponse**](ApiListTagsResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **tag_service_unbind_tags**
> ApiUnbindTagsResponse tag_service_unbind_tags(body)



批量从照片解绑标签

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TagServiceApi()
body = swagger_client.ApiUnbindTagsRequest() # ApiUnbindTagsRequest | 

try:
    api_response = api_instance.tag_service_unbind_tags(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TagServiceApi->tag_service_unbind_tags: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUnbindTagsRequest**](ApiUnbindTagsRequest.md)|  | 

### Return type

[**ApiUnbindTagsResponse**](ApiUnbindTagsResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

