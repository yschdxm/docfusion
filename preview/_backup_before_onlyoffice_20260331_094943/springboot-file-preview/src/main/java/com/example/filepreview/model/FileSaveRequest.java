package com.example.filepreview.model;

public class FileSaveRequest {
    private String content;
    private String previewType;

    public FileSaveRequest() {
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public String getPreviewType() {
        return previewType;
    }

    public void setPreviewType(String previewType) {
        this.previewType = previewType;
    }
}