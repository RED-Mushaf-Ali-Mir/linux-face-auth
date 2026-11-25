#define PMA_SM_AUTH
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <syslog.h>
#include <stddef.h>

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh , int flags , int argc , const char **argv){
	(void) flags;
	
	const char *user = NULL;
	if (pam_get_user(pamh, &user , NULL) != PAM_SUCCESS)
		return PAM_AUTHINFO_UNAVAIL;
	
	const void * item = NULL;
	const char * service = "?";
	
	if (pam_get_item(pamh , PAM_SERVICE , &item) == PAM_SUCCESS && item != NULL)
		service = (const char *) item;
		
	pam_syslog (pamh , LOG_INFO , "Face module called: user =%s service = %s argc=%d" , user , service , argc);
	
	for(int i=0 ; i < argc; i++)
		pam_syslog(pamh , LOG_INFO , "arg[%d] = %s" , i , argv[i]);
	
	return PAM_IGNORE;
			
}

PAM_EXTERN int pam_sm_setcred (pam_handle_t *pamh , int flags , int argc , const char **argv)
{
	(void)pamh;(void) flags; (void)argc ; (void)argv;
	return PAM_SUCCESS;
}
