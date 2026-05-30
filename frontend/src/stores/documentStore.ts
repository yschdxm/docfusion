import { create } from 'zustand'
import toast from 'react-hot-toast'
import api from '../services/api'

export interface DocumentInfo {
  id: string
  filename: string
  original_filename: string
  file_type: string
  doc_category: string  // 'source' | 'template'
  file_size?: number
  status: string
  created_at: string
  extraction_status?: {
    task_id: string
    status: 'queued' | 'processing' | 'completed' | 'failed'
    progress: string
    current_step: string
    error?: string
    entities_count: number
  } | null
}

interface DocumentStore {
  documents: DocumentInfo[]
  isLoading: boolean
  uploadProgress: number | null  // 上传进度 0-100，null 表示未上传中
  fetchDocuments: (category?: string) => Promise<void>
  addDocuments: (files: File[], category?: string) => Promise<DocumentInfo[]>
  deleteDocument: (id: string) => Promise<void>
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
      toast.error('获取文件列表失败，请刷新页面重试')
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
}))
