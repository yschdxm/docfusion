import { create } from 'zustand'
import toast from 'react-hot-toast'
import api from '../services/api'
import { tr } from '../services/i18n'

export interface DocumentInfo {
  id: string
  filename: string
  original_filename: string
  file_type: string
  doc_category: string  // 'source' | 'template' | 'output'
  file_size?: number
  status: string
  created_at: string
  user_id?: string | null
  is_shared?: boolean
  root_document_id?: string
  version?: number
  version_count?: number
  origin_type?: string | null
  origin_label?: string | null
  origin_conversation_id?: string | null
  extraction_status?: {
    task_id: string
    status: 'queued' | 'processing' | 'completed' | 'failed'
    progress: string
    current_step: string
    error?: string
    entities_count: number
  } | null
}

export interface DocumentVersion {
  id: string
  version: number
  is_latest: boolean
  origin_type?: string | null
  origin_label?: string | null
  origin_conversation_id?: string | null
  file_size?: number
  status: string
  created_at: string
  download_url: string
}

interface DocumentStore {
  documents: DocumentInfo[]
  isLoading: boolean
  uploadProgress: number | null  // 上传进度 0-100，null 表示未上传中
  fetchDocuments: (category?: string) => Promise<void>
  addDocuments: (files: File[], category?: string) => Promise<DocumentInfo[]>
  deleteDocument: (id: string) => Promise<void>
  fetchVersions: (id: string) => Promise<DocumentVersion[]>
  rollbackDocument: (id: string, versionId: string) => Promise<void>
  deleteVersion: (id: string, versionId: string) => Promise<void>
}

export const useDocumentStore = create<DocumentStore>((set) => ({
  documents: [],
  isLoading: false,
  uploadProgress: null,

  fetchDocuments: async (category?: string) => {
    set({ isLoading: true })
    try {
      const url = category ? `/documents?doc_category=${category}` : '/documents'
      const response = await api.get(url)
      if (category) {
        set({ documents: response.data || [] })
      } else {
        set({ documents: response.data || [] })
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error)
      toast.error(tr('获取文件列表失败，请刷新页面重试', 'Failed to fetch documents, please refresh the page', '文書一覧の取得に失敗しました。ページを更新してください'))
    } finally {
      set({ isLoading: false })
    }
  },

  addDocuments: async (files: File[], category: string = 'source') => {
    const formData = new FormData()
    files.forEach((file) => {
      formData.append('files', file)
    })

    set({ uploadProgress: 0 })

    try {
      const response = await api.post(`/documents/upload?doc_category=${category}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            set({ uploadProgress: percent })
          }
        },
      })
      const newDocs = response.data || []
      // 为 source 类型文档预设排队状态，避免显示"待提取"
      const docsWithStatus = newDocs.map((doc: DocumentInfo) => {
        if (category === 'source') {
          return {
            ...doc,
            extraction_status: {
              task_id: '',
              status: 'queued' as const,
              progress: '0%',
              current_step: '等待处理...',
              entities_count: 0,
            },
          }
        }
        return doc
      })
      set((state) => ({ documents: [...state.documents, ...docsWithStatus], uploadProgress: null }))
      return docsWithStatus
    } catch (error) {
      set({ uploadProgress: null })
      console.error('Failed to upload documents:', error)
      throw error
    }
  },

  deleteDocument: async (id: string) => {
    try {
      await api.delete(`/documents/${id}`)
      set((state) => ({
        documents: state.documents.filter((doc) => doc.id !== id),
      }))
    } catch (error) {
      console.error('Failed to delete document:', error)
      throw error
    }
  },

  fetchVersions: async (id: string) => {
    const response = await api.get(`/documents/${id}/versions`)
    return (response.data || []) as DocumentVersion[]
  },

  rollbackDocument: async (id: string, versionId: string) => {
    await api.post(`/documents/${id}/rollback/${versionId}`)
  },

  deleteVersion: async (id: string, versionId: string) => {
    await api.delete(`/documents/${id}/versions/${versionId}`)
  },
}))
