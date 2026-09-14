'use client';
import { useLHSession } from '@components/Contexts/LHSessionContext';
import { useOrg } from '@components/Contexts/OrgContext';
import { Breadcrumbs } from '@components/Objects/Breadcrumbs/Breadcrumbs'
import {
  approveCourseAccessRequest,
  listCourseAccessRequests,
  rejectCourseAccessRequest,
} from '@services/courses/accessRequests';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Inbox, Lock, X } from 'lucide-react';
import React, { useState } from 'react'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next';

function AccessRequestsHome() {
  const { t } = useTranslation()
  const session = useLHSession() as any;
  const access_token = session?.data?.tokens?.access_token;
  const org = useOrg() as any;
  const queryClient = useQueryClient();
  const [pendingActionId, setPendingActionId] = useState<number | null>(null)

  const queryKey = ['course-access-requests', org?.id]

  const { data: requestsResult, isLoading } = useQuery({
    queryKey,
    queryFn: () => listCourseAccessRequests(org.id, access_token, 'PENDING'),
    enabled: !!(org?.id && access_token),
    staleTime: 30_000,
  })

  // These endpoints return the resource directly (a bare array / object),
  // not the {success, data} envelope some other API calls in this codebase
  // use -- that shape comes from those specific endpoints' own response
  // bodies, not from errorHandling(), which just returns res.json() as-is.
  const requests: any[] = Array.isArray(requestsResult) ? requestsResult : []

  const decide = async (id: number, action: 'approve' | 'reject') => {
    if (pendingActionId) return
    setPendingActionId(id)
    try {
      await (action === 'approve'
        ? approveCourseAccessRequest(id, access_token)
        : rejectCourseAccessRequest(id, access_token))
      toast.success(
        action === 'approve'
          ? t('dashboard.access_requests.approved', 'Access approved')
          : t('dashboard.access_requests.rejected', 'Request rejected')
      )
      queryClient.invalidateQueries({ queryKey })
    } catch {
      toast.error(t('dashboard.access_requests.action_failed', 'Something went wrong'))
    } finally {
      setPendingActionId(null)
    }
  }

  return (
    <div className='flex w-full'>
      <div className='ps-4 sm:ps-10 me-4 sm:me-10 tracking-tighter flex flex-col space-y-5 w-full'>
        <div className='flex flex-col space-y-2 pt-6'>
          <Breadcrumbs items={[
            { label: t('dashboard.access_requests.nav_label', 'Access requests'), href: '/dash/access-requests', icon: <Lock size={14} /> }
          ]} />
          <h1 className="pt-3 flex font-bold text-4xl">{t('dashboard.access_requests.title', 'Access requests')}</h1>
          <p className="text-sm text-gray-500">
            {t(
              'dashboard.access_requests.subtitle',
              'Learners who requested access to a restricted course. Approving adds them to the course\'s access group.'
            )}
          </p>
        </div>

        {isLoading && (
          <div className="animate-pulse space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-gray-100 rounded-xl" />
            ))}
          </div>
        )}

        {!isLoading && requests.length === 0 && (
          <div className='flex flex-col items-center justify-center py-16 text-gray-400 gap-3'>
            <div className='bg-gray-100 rounded-2xl p-4'>
              <Inbox size={28} />
            </div>
            <p className='text-sm font-semibold'>
              {t('dashboard.access_requests.empty', 'No pending requests')}
            </p>
          </div>
        )}

        <div className='flex flex-col gap-2'>
          {requests.map((req: any) => (
            <div
              key={req.id}
              className='flex items-center justify-between gap-4 bg-white nice-shadow rounded-xl px-4 py-3'
            >
              <div className='flex flex-col min-w-0'>
                <p className='font-semibold text-gray-900 truncate'>{req.course_name}</p>
                <p className='text-xs text-gray-500 truncate'>
                  {req.user_username || req.user_email} · {req.user_email}
                </p>
              </div>
              <div className='flex items-center gap-2 flex-none'>
                <button
                  onClick={() => decide(req.id, 'reject')}
                  disabled={pendingActionId === req.id}
                  className='inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors disabled:opacity-50'
                >
                  <X size={14} />
                  {t('dashboard.access_requests.reject', 'Reject')}
                </button>
                <button
                  onClick={() => decide(req.id, 'approve')}
                  disabled={pendingActionId === req.id}
                  className='inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg bg-black text-white hover:bg-gray-800 transition-colors disabled:opacity-50'
                >
                  <Check size={14} />
                  {t('dashboard.access_requests.approve', 'Approve')}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default AccessRequestsHome
