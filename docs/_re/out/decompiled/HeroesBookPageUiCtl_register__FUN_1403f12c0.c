// FUN_1403f12c0 @ 0x1403f12c0
// purpose-guess: HeroesBookPageUiCtl_register
// callers (0):


void FUN_1403f12c0(undefined8 *param_1,longlong param_2)

{
  char *pcVar1;
  int iVar2;
  char *_Buf1;
  longlong lVar3;
  longlong lVar4;
  char *local_28;
  uint local_20;
  char *local_18;
  undefined4 local_10;
  
  lVar3 = -1;
  lVar4 = -1;
  pcVar1 = (char *)**(undefined8 **)(param_2 + 8);
  _Buf1 = "";
  if (*pcVar1 != '\0') {
    _Buf1 = pcVar1;
  }
  do {
    lVar4 = lVar4 + 1;
  } while (pcVar1[lVar4] != '\0');
  if ((((uint)lVar4 & 0x7fffffff) == 0x2c) &&
     (iVar2 = memcmp(_Buf1,"EntityCpntHeroesBookPageUiControllerSettings",
                     (ulonglong)((uint)lVar4 & 0x7fffffff)), iVar2 == 0)) {
    lVar4 = (**(code **)*param_1)(param_1);
    pcVar1 = *(char **)(lVar4 + 8);
    local_28 = "";
    if (*pcVar1 != '\0') {
      local_28 = pcVar1;
    }
    do {
      lVar3 = lVar3 + 1;
    } while (pcVar1[lVar3] != '\0');
    local_18 = "EntityCpntHeroesBookPageUiControllerSettings";
    local_10 = 0x8000002c;
    local_20 = ((uint)lVar3 ^ *(uint *)(lVar4 + 0x10)) & 0x7fffffff ^ *(uint *)(lVar4 + 0x10);
    FUN_1404e4cf0(param_2,&local_18,&local_28);
  }
  else {
    FUN_1403d5e60(param_1,param_2);
  }
  return;
}

