#define PAM_SM_AUTH
#define DEFAULT_HELPER "/opt/face-auth/face_auth"
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <syslog.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <errno.h>
#include <stdlib.h>

struct config {const char *user;  const char* service; const char* helper;};

static const char* arg_value(const char* arg , const char* key){
	size_t n = strlen(key);

	if (strncmp(arg , key , n) == 0 && arg[n] == '=')
		return arg + n + 1;
		
	return NULL;

}

static int parse_args (pam_handle_t* pamh , int argc , const char **argv , struct config * cfg){
	
	cfg -> user = NULL; cfg -> service = NULL; cfg -> helper = NULL;

	for (int i = 0 ; i < argc ; i++){
		const char* v = arg_value(argv[i] ,"user");
		if (v != NULL){
			cfg -> user = v;
			continue;
			}
		v = arg_value(argv[i] ,"service");	
		if (v != NULL){
			cfg  -> service = v;
			continue;
			}
		v = arg_value(argv[i] ,"helper");	
		if ( v != NULL){
		    cfg -> helper = v;
            continue;
		    }
		 
		else{
			pam_syslog(pamh , LOG_ERR , "Unknown option : %s" , argv[i]);
			return -1;
		}
		}
	
	if (cfg -> user == NULL){
		pam_syslog(pamh , LOG_ERR,  "Error missing Inputs user");
		return -1;
	}
	else if(cfg -> service == NULL){
		pam_syslog(pamh , LOG_ERR,  "Error missing Inputs Service");
		return -1;
	}else if (cfg -> helper == NULL ){
	    cfg -> helper = DEFAULT_HELPER;
	    pam_syslog(pamh , LOG_INFO , "No helper Default helper used : %s" ,DEFAULT_HELPER);
	}
	
	if (cfg -> helper[0] != '/'){
	    pam_syslog(pamh , LOG_ERR , "Helper must be absolute path");
	        return -1;
	}
	return 0;
	
	
}



PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh , int flags , int argc , const char **argv){
	(void) flags;
	struct config cfg;
	
	int parsed_out = parse_args(pamh , argc , argv , &cfg);
		
	if (parsed_out == -1){
		pam_syslog(pamh , LOG_ERR  , "Parsing Failed");
		return PAM_SERVICE_ERR;
	}
	const char *user = NULL;
	if (pam_get_user(pamh, &user , NULL) != PAM_SUCCESS)
		return PAM_AUTHINFO_UNAVAIL;
	
	const void * item = NULL;
	const char * service = "?";
	
	if (pam_get_item(pamh , PAM_SERVICE , &item) == PAM_SUCCESS && item != NULL)
		service = (const char *) item;
	if (strcmp(user , cfg.user) != 0 ){
		pam_syslog(pamh , LOG_ERR , "User mismatch");
		return PAM_IGNORE;}
	if(strcmp(service , cfg.service) != 0){
		pam_syslog(pamh , LOG_ERR , "Service mismatch");
		return PAM_IGNORE;}
	
	pam_syslog (pamh , LOG_INFO , "Face module called: user =%s service = %s argc=%d" , user , service , argc);
	
	pam_syslog(pamh , LOG_INFO , "Gaurd Passed");
	
	return PAM_IGNORE;
			
}

PAM_EXTERN int pam_sm_setcred (pam_handle_t *pamh , int flags , int argc , const char **argv)
{
	(void)pamh;(void) flags; (void)argc ; (void)argv;
	return PAM_SUCCESS;
}


///////////////////////////////////////////////////////////////

