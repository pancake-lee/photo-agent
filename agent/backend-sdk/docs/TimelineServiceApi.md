# swagger_client.TimelineServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**timeline_service_get_photos_by_timeline**](TimelineServiceApi.md#timeline_service_get_photos_by_timeline) | **GET** /api/v1/timelines/{name}/photos | 
[**timeline_service_list_timelines**](TimelineServiceApi.md#timeline_service_list_timelines) | **GET** /api/v1/timelines | 

# **timeline_service_get_photos_by_timeline**
> ApiGetPhotosByTimelineResponse timeline_service_get_photos_by_timeline(name)



某时间线下的照片

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TimelineServiceApi()
name = 'name_example' # str | 

try:
    api_response = api_instance.timeline_service_get_photos_by_timeline(name)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_get_photos_by_timeline: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **name** | **str**|  | 

### Return type

[**ApiGetPhotosByTimelineResponse**](ApiGetPhotosByTimelineResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **timeline_service_list_timelines**
> ApiListTimelinesResponse timeline_service_list_timelines()



所有时间线列表

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TimelineServiceApi()

try:
    api_response = api_instance.timeline_service_list_timelines()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_list_timelines: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiListTimelinesResponse**](ApiListTimelinesResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

