import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const listDocuments = vi.fn()
const uploadDocument = vi.fn()
const getDocument = vi.fn()

vi.mock('@/api/client', () => {
  class ApiError extends Error {
    status: number
    detail: string
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
      this.detail = detail
    }
  }
  return {
    ApiError,
    api: { listDocuments: (...a: unknown[]) => listDocuments(...a),
           uploadDocument: (...a: unknown[]) => uploadDocument(...a),
           getDocument: (...a: unknown[]) => getDocument(...a) },
  }
})

import DocumentList from '@/components/DocumentList.vue'
import { ApiError } from '@/api/client'

beforeEach(() => {
  listDocuments.mockReset(); uploadDocument.mockReset(); getDocument.mockReset()
  getDocument.mockResolvedValue({ id: 1, processing_status: 'ready' })
})

describe('DocumentList', () => {
  it('shows live embedding progress for an indexing document', async () => {
    listDocuments.mockResolvedValue([
      { id: 1, vehicle_id: 1, file_name: 'm.pdf', document_type: 'service_manual',
        processing_status: 'pending', uploaded_utc: '2026-06-20', chunks_total: 5, chunks_done: 3 },
    ])
    const wrapper = mount(DocumentList, { props: { vehicleId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('EMBEDDING 3/5')
  })

  it('surfaces an upload error in the UI instead of failing silently', async () => {
    listDocuments.mockResolvedValue([])
    uploadDocument.mockRejectedValue(new ApiError(413, 'File is larger than the 600 MB upload limit.'))
    const wrapper = mount(DocumentList, { props: { vehicleId: 1 } })
    await flushPromises()

    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['x'], 'big.pdf', { type: 'application/pdf' })],
    })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('Upload failed')
    expect(wrapper.text()).toContain('600 MB upload limit')
  })
})
