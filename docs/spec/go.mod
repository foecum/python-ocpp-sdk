// This empty module keeps the OCPP specifications (about 80 MB of PDF, zip and
// spreadsheet files) out of the github.com/foecum/go-ocpp-sdk module: Go leaves
// a directory with its own go.mod out of the parent module's download. The files
// stay in the repository, where the generator and the schema tests read them.
module github.com/foecum/go-ocpp-sdk/docs/spec

go 1.27
