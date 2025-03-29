{{/*
HELPER FUNCTIONS FOR MIGHTY HELM CHART!
*/}}
{{/* GET CHART NAME */}}
{{- define "terminal-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* CREATE FULLNAME WITH RELEASE NAME */}}
{{- define "terminal-operator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/* GET SERVICE ACCOUNT NAME */}}
{{- define "terminal-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "terminal-operator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}