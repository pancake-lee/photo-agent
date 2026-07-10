# swagger_client.PhotoServiceApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**photo_service_delete_photo**](PhotoServiceApi.md#photo_service_delete_photo) | **DELETE** /api/v1/photos/{id} | 
[**photo_service_get_photo_detail**](PhotoServiceApi.md#photo_service_get_photo_detail) | **GET** /api/v1/photos/{id} | 
[**photo_service_get_photo_stats**](PhotoServiceApi.md#photo_service_get_photo_stats) | **GET** /api/v1/photos/stats | 
[**photo_service_search_photos**](PhotoServiceApi.md#photo_service_search_photos) | **GET** /api/v1/photos | 
[**photo_service_update_photo_tags**](PhotoServiceApi.md#photo_service_update_photo_tags) | **PUT** /api/v1/photos/{id}/tags | 

# **photo_service_delete_photo**
> ApiDeletePhotoResponse photo_service_delete_photo(id)



删除照片（含文件清理）

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.PhotoServiceApi()
id = 'id_example' # str | 

try:
    api_response = api_instance.photo_service_delete_photo(id)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling PhotoServiceApi->photo_service_delete_photo: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id** | **str**|  | 

### Return type

[**ApiDeletePhotoResponse**](ApiDeletePhotoResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **photo_service_get_photo_detail**
> ApiGetPhotoDetailResponse photo_service_get_photo_detail(id)



单张详情

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.PhotoServiceApi()
id = 'id_example' # str | 

try:
    api_response = api_instance.photo_service_get_photo_detail(id)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling PhotoServiceApi->photo_service_get_photo_detail: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id** | **str**|  | 

### Return type

[**ApiGetPhotoDetailResponse**](ApiGetPhotoDetailResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **photo_service_get_photo_stats**
> ApiGetPhotoStatsResponse photo_service_get_photo_stats()



综合统计

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.PhotoServiceApi()

try:
    api_response = api_instance.photo_service_get_photo_stats()
    pprint(api_response)
except ApiException as e:
    print("Exception when calling PhotoServiceApi->photo_service_get_photo_stats: %s\n" % e)
```

### Parameters
This endpoint does not need any parameter.

### Return type

[**ApiGetPhotoStatsResponse**](ApiGetPhotoStatsResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **photo_service_search_photos**
> ApiSearchPhotosResponse photo_service_search_photos(page=page, page_size=page_size, timeline=timeline, tag=tag, keyword=keyword, brand=brand, lens=lens, focal_min=focal_min, focal_max=focal_max, iso_min=iso_min, iso_max=iso_max, shot_at_start=shot_at_start, shot_at_end=shot_at_end, sort_by=sort_by, sort_order=sort_order)



复杂条件分页查询

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.PhotoServiceApi()
page = 56 # int |  (optional)
page_size = 56 # int |  (optional)
timeline = 'timeline_example' # str |  (optional)
tag = 'tag_example' # str |  (optional)
keyword = 'keyword_example' # str |  (optional)
brand = 'brand_example' # str |  (optional)
lens = 'lens_example' # str |  (optional)
focal_min = 'focal_min_example' # str |  (optional)
focal_max = 'focal_max_example' # str |  (optional)
iso_min = 56 # int |  (optional)
iso_max = 56 # int |  (optional)
shot_at_start = 'shot_at_start_example' # str |  (optional)
shot_at_end = 'shot_at_end_example' # str |  (optional)
sort_by = 'sort_by_example' # str |  (optional)
sort_order = 'sort_order_example' # str |  (optional)

try:
    api_response = api_instance.photo_service_search_photos(page=page, page_size=page_size, timeline=timeline, tag=tag, keyword=keyword, brand=brand, lens=lens, focal_min=focal_min, focal_max=focal_max, iso_min=iso_min, iso_max=iso_max, shot_at_start=shot_at_start, shot_at_end=shot_at_end, sort_by=sort_by, sort_order=sort_order)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling PhotoServiceApi->photo_service_search_photos: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **page** | **int**|  | [optional] 
 **page_size** | **int**|  | [optional] 
 **timeline** | **str**|  | [optional] 
 **tag** | **str**|  | [optional] 
 **keyword** | **str**|  | [optional] 
 **brand** | **str**|  | [optional] 
 **lens** | **str**|  | [optional] 
 **focal_min** | **str**|  | [optional] 
 **focal_max** | **str**|  | [optional] 
 **iso_min** | **int**|  | [optional] 
 **iso_max** | **int**|  | [optional] 
 **shot_at_start** | **str**|  | [optional] 
 **shot_at_end** | **str**|  | [optional] 
 **sort_by** | **str**|  | [optional] 
 **sort_order** | **str**|  | [optional] 

### Return type

[**ApiSearchPhotosResponse**](ApiSearchPhotosResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **photo_service_update_photo_tags**
> ApiEmpty photo_service_update_photo_tags(body, id)



更新标签

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.PhotoServiceApi()
body = swagger_client.ApiUpdatePhotoTagsRequest() # ApiUpdatePhotoTagsRequest | 
id = 'id_example' # str | 

try:
    api_response = api_instance.photo_service_update_photo_tags(body, id)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling PhotoServiceApi->photo_service_update_photo_tags: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdatePhotoTagsRequest**](ApiUpdatePhotoTagsRequest.md)|  | 
 **id** | **str**|  | 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

