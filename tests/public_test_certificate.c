/* Public test fixture. Never use for release credentials. */
#include <stdio.h>
#include <stdlib.h>

#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/x509.h>
#include <openssl/x509v3.h>

static void require(int success, const char *step) {
  if (!success) {
    fprintf(stderr, "TEST_CERTIFICATE_FAILURE %s\n", step);
    ERR_print_errors_fp(stderr);
    exit(1);
  }
}

static void extension(X509 *certificate, X509V3_CTX *context, int nid,
                      const char *value) {
  X509_EXTENSION *item = X509V3_EXT_conf_nid(NULL, context, nid, value);
  require(item != NULL, "extension_create");
  require(X509_add_ext(certificate, item, -1) == 1, "extension_add");
  X509_EXTENSION_free(item);
}

int main(int argc, char **argv) {
  require(argc == 4, "arguments");
  require(OPENSSL_init_crypto(OPENSSL_INIT_NO_LOAD_CONFIG, NULL) == 1, "initialize");
  BIO *input = BIO_new_file(argv[1], "rb");
  require(input != NULL, "public_fixture_key_open");
  EVP_PKEY *key = PEM_read_bio_PrivateKey(input, NULL, NULL, NULL);
  BIO_free(input);
  require(key != NULL && EVP_PKEY_base_id(key) == EVP_PKEY_RSA &&
              EVP_PKEY_bits(key) >= 2048,
          "public_fixture_rsa_key");
  X509 *certificate = X509_new();
  require(certificate != NULL, "certificate_create");
  require(X509_set_version(certificate, 2) == 1, "version");
  require(ASN1_INTEGER_set(X509_get_serialNumber(certificate), 1) == 1, "serial");
  require(ASN1_TIME_set_string_X509(X509_getm_notBefore(certificate), "20260101000000Z") == 1,
          "not_before");
  require(ASN1_TIME_set_string_X509(X509_getm_notAfter(certificate), "20360101000000Z") == 1,
          "not_after");
  require(X509_set_pubkey(certificate, key) == 1, "public_key");
  X509_NAME *subject = X509_get_subject_name(certificate);
  require(X509_NAME_add_entry_by_txt(subject, "CN", MBSTRING_ASC,
                                    (const unsigned char *)"Example", -1, -1, 0) == 1,
          "subject");
  require(X509_set_issuer_name(certificate, subject) == 1, "issuer");
  X509V3_CTX context;
  X509V3_set_ctx(&context, certificate, certificate, NULL, NULL, 0);
  extension(certificate, &context, NID_basic_constraints, "critical,CA:FALSE");
  extension(certificate, &context, NID_key_usage, "critical,digitalSignature");
  extension(certificate, &context, NID_ext_key_usage, "codeSigning");
  extension(certificate, &context, NID_subject_key_identifier, "hash");
  extension(certificate, &context, NID_authority_key_identifier, "keyid:always");
  require(X509_sign(certificate, key, EVP_sha256()) > 0, "sign");
  BIO *pem = BIO_new_file(argv[2], "wb");
  require(pem != NULL && PEM_write_bio_X509(pem, certificate) == 1, "pem_write");
  require(BIO_free(pem) == 1, "pem_close");
  BIO *der = BIO_new_file(argv[3], "wb");
  require(der != NULL && i2d_X509_bio(der, certificate) == 1, "der_write");
  require(BIO_free(der) == 1, "der_close");
  X509_free(certificate);
  EVP_PKEY_free(key);
  return 0;
}
