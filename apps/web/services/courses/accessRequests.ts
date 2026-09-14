import { RequestBodyWithAuthHeader, errorHandling } from '@services/utils/ts/requests'
import { getAPIUrl } from '@services/config/config'

export async function requestCourseAccess(course_uuid: string, access_token: any) {
  const result: any = await fetch(
    `${getAPIUrl()}courses/${course_uuid}/access_requests`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  const res = await errorHandling(result)
  return res
}

export async function listCourseAccessRequests(
  org_id: number,
  access_token: any,
  status_filter: string = 'PENDING'
) {
  const result: any = await fetch(
    `${getAPIUrl()}courses/access_requests/list?org_id=${org_id}&status_filter=${status_filter}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  const res = await errorHandling(result)
  return res
}

export async function approveCourseAccessRequest(request_id: number, access_token: any) {
  const result: any = await fetch(
    `${getAPIUrl()}courses/access_requests/${request_id}/approve`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  const res = await errorHandling(result)
  return res
}

export async function rejectCourseAccessRequest(request_id: number, access_token: any) {
  const result: any = await fetch(
    `${getAPIUrl()}courses/access_requests/${request_id}/reject`,
    RequestBodyWithAuthHeader('POST', null, null, access_token)
  )
  const res = await errorHandling(result)
  return res
}
