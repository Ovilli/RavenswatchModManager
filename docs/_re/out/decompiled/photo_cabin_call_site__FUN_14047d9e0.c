// photo_cabin_call_site
// caller site (link va): 0x14047da18
// containing function: FUN_14047d9e0 @ 0x14047d9e0


longlong FUN_14047d9e0(longlong param_1,undefined8 *param_2,undefined8 *param_3,undefined8 param_4)

{
  undefined1 uVar1;
  
  FUN_1401145b0();
  FUN_1401145b0(param_1 + 0x10,param_3);
  *(undefined8 *)(param_1 + 0x20) = param_4;
  if ((*(char *)*param_2 == '\0') && (*(char *)*param_3 == '\0')) {
    uVar1 = 1;
  }
  else {
    uVar1 = 0;
  }
  *(undefined1 *)(param_1 + 0x28) = uVar1;
  return param_1;
}

