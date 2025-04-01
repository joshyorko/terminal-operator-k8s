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

{{/* Common labels */}}
{{- define "terminal-operator.labels" -}}
helm.sh/chart: {{ include "terminal-operator.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "terminal-operator.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Selector labels */}}
{{- define "terminal-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "terminal-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* GET SERVICE ACCOUNT NAME */}}
{{- define "terminal-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "terminal-operator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}