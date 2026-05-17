// FUN_1406c7050 @ 0x1406c7050
// purpose-guess: oCEntitySettings_setname_cb
// callers (1):
//   FUN_140186fc0 @ 140186fc0


void FUN_1406c7050(longlong *param_1)

{
  char *local_18;
  undefined4 local_10;
  
  local_10 = 0x8000000f;
  local_18 = "Entity Settings";
  (**(code **)(*param_1 + 0x18))(param_1,&local_18);
  *(undefined4 *)param_1[0x11] = 0x80001;
  return;
}

