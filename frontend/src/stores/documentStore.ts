import { create } from 'zustand'
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
}

interface DocumentStore {
  documents: DocumentInfo[]
  isLoading: boolean
  fetchDocuments: (category?: string) => Promise<void>
  addDocuments: (files: File[], category?: string) => Promise<DocumentInfo[]>
  deleteDocument: (id: string) => Promise<void>
}

export const useDocumentStore = create<DocumentStore>((set, get) => ({
  documents: [],
  isLoading: false,

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
    } finally {
      set({ isLoading: false })
    }
  },

  addDocuments: async (files: File[], category: string = 'source') => {
    const formData = new FormData()
    files.forEach((file) => {
      formData.append('files', file)
    })

    try {
      const response = await api.post(`/documents/upload?doc_category=${category}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const newDocs = response.data || []
      set((state) => ({ documents: [...state.documents, ...newDocs] }))
      return newDocs
    } catch (error) {
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
