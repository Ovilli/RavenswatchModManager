// FUN_140421d20 @ 0x140421d20
// purpose-guess: DtSocialBookPage_factory_candidate
// callers (1):
//   FUN_140405b80 @ 140405b80


void FUN_140421d20(longlong *param_1)

{
  char *local_18;
  undefined4 local_10;
  
  local_10 = 0x80000013;
  local_18 = "Dt Social Book Page";
  (**(code **)(*param_1 + 0x18))(param_1,&local_18);
  *(undefined4 *)param_1[0x11] = 0x10001;
  return;
}

