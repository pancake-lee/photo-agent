# swagger_client.TimelineServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**timeline_service_delete_event**](TimelineServiceApi.md#timeline_service_delete_event) | **DELETE** /api/v1/timeline-events/{id} | 
[**timeline_service_get_photos_by_timeline**](TimelineServiceApi.md#timeline_service_get_photos_by_timeline) | **GET** /api/v1/timelines/{name}/photos | 
[**timeline_service_get_recompute_timelines_status**](TimelineServiceApi.md#timeline_service_get_recompute_timelines_status) | **GET** /api/v1/timeline-events/recompute/status | 
[**timeline_service_list_events**](TimelineServiceApi.md#timeline_service_list_events) | **GET** /api/v1/timeline-events | 
[**timeline_service_list_timelines**](TimelineServiceApi.md#timeline_service_list_timelines) | **GET** /api/v1/timelines | 
[**timeline_service_recompute_timelines**](TimelineServiceApi.md#timeline_service_recompute_timelines) | **POST** /api/v1/timeline-events/recompute | 
[**timeline_service_save_event**](TimelineServiceApi.md#timeline_service_save_event) | **POST** /api/v1/timeline-events | 

# **timeline_service_delete_event**
> ApiEmpty timeline_service_delete_event(id)



删除时间线事件

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TimelineServiceApi()
id = 'id_example' # str | 

try:
    api_response = api_instance.timeline_service_delete_event(id)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_delete_event: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id** | **str**|  | 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

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

# **timeline_service_get_recompute_timelines_status**
> ApiGetRecomputeTimelinesStatusResponse timeline_service_get_recompute_timelines_status()



查询重算进度

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
    api_response = api_instance.timeline_service_get_recompute_timelines_status()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_get_recompute_timelines_status: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetRecomputeTimelinesStatusResponse**](ApiGetRecomputeTimelinesStatusResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **timeline_service_list_events**
> ApiListTimelineEventsResponse timeline_service_list_events()



时间线事件列表（含散片组只读展示）

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
    api_response = api_instance.timeline_service_list_events()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_list_events: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiListTimelineEventsResponse**](ApiListTimelineEventsResponse.md)

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

# **timeline_service_recompute_timelines**
> ApiRecomputeTimelinesResponse timeline_service_recompute_timelines(body)



触发全量重算照片 timeline（异步，人工值保留）

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TimelineServiceApi()
body = swagger_client.ApiEmpty() # ApiEmpty | 

try:
    api_response = api_instance.timeline_service_recompute_timelines(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_recompute_timelines: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiEmpty**](ApiEmpty.md)|  | 

### Return type

[**ApiRecomputeTimelinesResponse**](ApiRecomputeTimelinesResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **timeline_service_save_event**
> ApiSaveTimelineEventResponse timeline_service_save_event(body)



保存时间线事件（新建与更新合一，id 为空则新建）

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.TimelineServiceApi()
body = swagger_client.ApiSaveTimelineEventRequest() # ApiSaveTimelineEventRequest | 

try:
    api_response = api_instance.timeline_service_save_event(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling TimelineServiceApi->timeline_service_save_event: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiSaveTimelineEventRequest**](ApiSaveTimelineEventRequest.md)|  | 

### Return type

[**ApiSaveTimelineEventResponse**](ApiSaveTimelineEventResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

