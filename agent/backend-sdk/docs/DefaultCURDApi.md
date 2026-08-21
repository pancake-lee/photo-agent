# swagger_client.DefaultCURDApi

All URIs are relative to *http://127.0.0.1:8080*

Method | HTTP request | Description
------------- | ------------- | -------------
[**default_curd_add_app_setting**](DefaultCURDApi.md#default_curd_add_app_setting) | **POST** /app-settings | 
[**default_curd_add_photo**](DefaultCURDApi.md#default_curd_add_photo) | **POST** /photos | 
[**default_curd_add_photo_group**](DefaultCURDApi.md#default_curd_add_photo_group) | **POST** /photo-groups | 
[**default_curd_add_timeline_event**](DefaultCURDApi.md#default_curd_add_timeline_event) | **POST** /timeline-events | 
[**default_curd_del_app_setting_by_key_list**](DefaultCURDApi.md#default_curd_del_app_setting_by_key_list) | **DELETE** /app-settings | 
[**default_curd_del_photo_by_id_list**](DefaultCURDApi.md#default_curd_del_photo_by_id_list) | **DELETE** /photos | 
[**default_curd_del_photo_group_by_id_list**](DefaultCURDApi.md#default_curd_del_photo_group_by_id_list) | **DELETE** /photo-groups | 
[**default_curd_del_timeline_event_by_id_list**](DefaultCURDApi.md#default_curd_del_timeline_event_by_id_list) | **DELETE** /timeline-events | 
[**default_curd_get_app_setting_list**](DefaultCURDApi.md#default_curd_get_app_setting_list) | **GET** /app-settings | 
[**default_curd_get_photo_group_list**](DefaultCURDApi.md#default_curd_get_photo_group_list) | **GET** /photo-groups | 
[**default_curd_get_photo_list**](DefaultCURDApi.md#default_curd_get_photo_list) | **GET** /photos | 
[**default_curd_get_timeline_event_list**](DefaultCURDApi.md#default_curd_get_timeline_event_list) | **GET** /timeline-events | 
[**default_curd_update_app_setting**](DefaultCURDApi.md#default_curd_update_app_setting) | **PATCH** /app-settings | 
[**default_curd_update_photo**](DefaultCURDApi.md#default_curd_update_photo) | **PATCH** /photos | 
[**default_curd_update_photo_group**](DefaultCURDApi.md#default_curd_update_photo_group) | **PATCH** /photo-groups | 
[**default_curd_update_timeline_event**](DefaultCURDApi.md#default_curd_update_timeline_event) | **PATCH** /timeline-events | 

# **default_curd_add_app_setting**
> ApiAddAppSettingResponse default_curd_add_app_setting(body)



--------------------------------------------------  tbl : app_settings

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiAddAppSettingRequest() # ApiAddAppSettingRequest | 

try:
    api_response = api_instance.default_curd_add_app_setting(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_add_app_setting: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiAddAppSettingRequest**](ApiAddAppSettingRequest.md)|  | 

### Return type

[**ApiAddAppSettingResponse**](ApiAddAppSettingResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_add_photo**
> ApiAddPhotoResponse default_curd_add_photo(body)



--------------------------------------------------  tbl : photos

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiAddPhotoRequest() # ApiAddPhotoRequest | 

try:
    api_response = api_instance.default_curd_add_photo(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_add_photo: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiAddPhotoRequest**](ApiAddPhotoRequest.md)|  | 

### Return type

[**ApiAddPhotoResponse**](ApiAddPhotoResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_add_photo_group**
> ApiAddPhotoGroupResponse default_curd_add_photo_group(body)



--------------------------------------------------  tbl : photo_groups

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiAddPhotoGroupRequest() # ApiAddPhotoGroupRequest | 

try:
    api_response = api_instance.default_curd_add_photo_group(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_add_photo_group: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiAddPhotoGroupRequest**](ApiAddPhotoGroupRequest.md)|  | 

### Return type

[**ApiAddPhotoGroupResponse**](ApiAddPhotoGroupResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_add_timeline_event**
> ApiAddTimelineEventResponse default_curd_add_timeline_event(body)



--------------------------------------------------  tbl : timeline_events

### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiAddTimelineEventRequest() # ApiAddTimelineEventRequest | 

try:
    api_response = api_instance.default_curd_add_timeline_event(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_add_timeline_event: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiAddTimelineEventRequest**](ApiAddTimelineEventRequest.md)|  | 

### Return type

[**ApiAddTimelineEventResponse**](ApiAddTimelineEventResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_del_app_setting_by_key_list**
> ApiEmpty default_curd_del_app_setting_by_key_list(key_list=key_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
key_list = ['key_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_del_app_setting_by_key_list(key_list=key_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_del_app_setting_by_key_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **key_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_del_photo_by_id_list**
> ApiEmpty default_curd_del_photo_by_id_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_del_photo_by_id_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_del_photo_by_id_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_del_photo_group_by_id_list**
> ApiEmpty default_curd_del_photo_group_by_id_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_del_photo_group_by_id_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_del_photo_group_by_id_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_del_timeline_event_by_id_list**
> ApiEmpty default_curd_del_timeline_event_by_id_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_del_timeline_event_by_id_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_del_timeline_event_by_id_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiEmpty**](ApiEmpty.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_get_app_setting_list**
> ApiGetAppSettingListResponse default_curd_get_app_setting_list(key_list=key_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
key_list = ['key_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_get_app_setting_list(key_list=key_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_get_app_setting_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **key_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiGetAppSettingListResponse**](ApiGetAppSettingListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_get_photo_group_list**
> ApiGetPhotoGroupListResponse default_curd_get_photo_group_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_get_photo_group_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_get_photo_group_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiGetPhotoGroupListResponse**](ApiGetPhotoGroupListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_get_photo_list**
> ApiGetPhotoListResponse default_curd_get_photo_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_get_photo_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_get_photo_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiGetPhotoListResponse**](ApiGetPhotoListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_get_timeline_event_list**
> ApiGetTimelineEventListResponse default_curd_get_timeline_event_list(id_list=id_list)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
id_list = ['id_list_example'] # list[str] |  (optional)

try:
    api_response = api_instance.default_curd_get_timeline_event_list(id_list=id_list)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_get_timeline_event_list: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **id_list** | [**list[str]**](str.md)|  | [optional] 

### Return type

[**ApiGetTimelineEventListResponse**](ApiGetTimelineEventListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_update_app_setting**
> ApiUpdateAppSettingResponse default_curd_update_app_setting(body)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiUpdateAppSettingRequest() # ApiUpdateAppSettingRequest | 

try:
    api_response = api_instance.default_curd_update_app_setting(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_update_app_setting: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdateAppSettingRequest**](ApiUpdateAppSettingRequest.md)|  | 

### Return type

[**ApiUpdateAppSettingResponse**](ApiUpdateAppSettingResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_update_photo**
> ApiUpdatePhotoResponse default_curd_update_photo(body)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiUpdatePhotoRequest() # ApiUpdatePhotoRequest | 

try:
    api_response = api_instance.default_curd_update_photo(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_update_photo: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdatePhotoRequest**](ApiUpdatePhotoRequest.md)|  | 

### Return type

[**ApiUpdatePhotoResponse**](ApiUpdatePhotoResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_update_photo_group**
> ApiUpdatePhotoGroupResponse default_curd_update_photo_group(body)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiUpdatePhotoGroupRequest() # ApiUpdatePhotoGroupRequest | 

try:
    api_response = api_instance.default_curd_update_photo_group(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_update_photo_group: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdatePhotoGroupRequest**](ApiUpdatePhotoGroupRequest.md)|  | 

### Return type

[**ApiUpdatePhotoGroupResponse**](ApiUpdatePhotoGroupResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **default_curd_update_timeline_event**
> ApiUpdateTimelineEventResponse default_curd_update_timeline_event(body)



### Example
```python
from __future__ import print_function
import time
import swagger_client
from swagger_client.rest import ApiException
from pprint import pprint

# create an instance of the API class
api_instance = swagger_client.DefaultCURDApi()
body = swagger_client.ApiUpdateTimelineEventRequest() # ApiUpdateTimelineEventRequest | 

try:
    api_response = api_instance.default_curd_update_timeline_event(body)
    pprint(api_response)
except ApiException as e:
    print("Exception when calling DefaultCURDApi->default_curd_update_timeline_event: %s\n" % e)
```

### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **body** | [**ApiUpdateTimelineEventRequest**](ApiUpdateTimelineEventRequest.md)|  | 

### Return type

[**ApiUpdateTimelineEventResponse**](ApiUpdateTimelineEventResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

